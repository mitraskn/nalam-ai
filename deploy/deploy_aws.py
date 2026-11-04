"""Put Nalam AI on AWS: one Lambda function with a public Function URL (a permanent link).

Run from the project folder (uses the `nalam` AWS profile). The app runs in Sydney (ap-southeast-2), the only region
this account may build in, and calls Amazon Bedrock in us-east-1 (BEDROCK_REGION), exactly like Uzhavan:
    .\\deploy.cmd            # create or update, prints the public link
    .\\deploy.cmd --delete   # remove everything after the hackathon

What it creates in ap-southeast-2:
  - IAM role `nalam-web-role`: may only call Amazon Bedrock models and write its own logs;
  - S3 bucket `nalam-web-<account>-ap-southeast-2` holding the code package (uploaded in small parts) and the
    family data and visit photos (family/, photos/), so they survive when Lambda starts a new copy;
  - Lambda function `nalam-web` (Python 3.12) running deploy/lambda_app.py = the same app as `.\\run_web`;
  - a public Function URL. No keys are in the function or the page. Each device may send 40 AI requests
    an hour, and (if the account allows) at most 5 copies run at once, to cap the cost.

deploy/deps.zip holds the Linux packages (strands-agents, boto3, pydantic, gTTS) for Python 3.12.
"""
from __future__ import annotations

import io
import json
import sys
import time
import zipfile
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config

ROOT = Path(__file__).resolve().parent.parent
REGION = "ap-southeast-2"   # this AWS account may only build in Sydney (like Uzhavan); the AI stays in us-east-1
BEDROCK_REGION = "us-east-1"
NAME, ROLE = "nalam-web", "nalam-web-role"
DEPS = ROOT / "deploy" / "deps.zip"
OUT = ROOT / "deploy" / "web.json"


def session():
    try:
        return boto3.Session(profile_name="nalam", region_name=REGION)
    except Exception:  # noqa: BLE001  no profile called nalam: use the default credentials
        return boto3.Session(region_name=REGION)


def build_zip() -> bytes:
    if not DEPS.exists():
        sys.exit(f"missing {DEPS}")
    buf = io.BytesIO(DEPS.read_bytes())
    with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED) as z:
        for p in (ROOT / "agent").rglob("*"):
            rel = p.relative_to(ROOT).as_posix()
            if p.is_file() and "__pycache__" not in rel and not rel.startswith("agent/data/family"):
                z.write(p, rel)
        for p in (ROOT / "web").glob("*"):
            z.write(p, p.relative_to(ROOT).as_posix())
        z.write(ROOT / "deploy" / "lambda_app.py", "lambda_app.py")
    return buf.getvalue()


def ensure_role(iam, bucket: str) -> str:
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
                                                       "Action": "sts:AssumeRole"}]}
    try:
        arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
        fresh = False
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust),
                              Description="Nalam AI web app: may only call Amazon Bedrock and write logs")["Role"]["Arn"]
        fresh = True
    iam.attach_role_policy(RoleName=ROLE, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
    iam.put_role_policy(RoleName=ROLE, PolicyName="bedrock-only", PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow",
                       "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream",
                                  "bedrock:Converse", "bedrock:ConverseStream"],
                       "Resource": "*"},
                      {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
                       "Resource": f"arn:aws:s3:::{bucket}/family/*"},
                      {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
                       "Resource": f"arn:aws:s3:::{bucket}/photos/*"},
                      {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": f"arn:aws:s3:::{bucket}"}]}))
    if fresh:
        print("[aws] new role: waiting 15 s for IAM to be ready...")
        time.sleep(15)
    return arn


def upload(sess, code: bytes) -> dict:
    acct = sess.client("sts").get_caller_identity()["Account"]
    bucket, key = f"nalam-web-{acct}-{REGION}", "nalam-web.zip"
    s3 = sess.client("s3", config=Config(retries={"max_attempts": 10, "mode": "adaptive"}))
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:  # noqa: BLE001  not there yet
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
    print(f"[aws] uploading the package ({len(code) / 1e6:.1f} MB) in small parts... (a few minutes on home internet)")
    s3.upload_fileobj(io.BytesIO(code), bucket, key,
                      Config=TransferConfig(multipart_threshold=5 * 1024 * 1024, multipart_chunksize=5 * 1024 * 1024,
                                            max_concurrency=2))
    print("[aws] uploaded")
    return {"S3Bucket": bucket, "S3Key": key}


def wait_ready(lam):
    for _ in range(60):
        c = lam.get_function_configuration(FunctionName=NAME)
        if c.get("State") == "Active" and c.get("LastUpdateStatus") in ("Successful", None):
            return
        time.sleep(3)


def deploy() -> None:
    sess = session()
    lam = sess.client("lambda")
    print("[aws] account:", sess.client("sts").get_caller_identity()["Account"], "region:", REGION)
    acct = sess.client("sts").get_caller_identity()["Account"]
    bucket = f"nalam-web-{acct}-{REGION}"
    role = ensure_role(sess.client("iam"), bucket)
    loc = upload(sess, build_zip())
    env = {"Variables": {"NALAM_DATA_DIR": "/tmp/nalam", "LIMIT_PER_HOUR": "40", "PYTHONIOENCODING": "utf-8",
                         "BEDROCK_REGION": BEDROCK_REGION, "NALAM_S3_BUCKET": bucket, "NALAM_TZ": "IST-5:30"}}
    try:
        lam.get_function(FunctionName=NAME)
        print("[aws] updating function")
        lam.update_function_code(FunctionName=NAME, **loc)
        wait_ready(lam)
        lam.update_function_configuration(FunctionName=NAME, Role=role, Timeout=90, MemorySize=1024, Environment=env)
    except lam.exceptions.ResourceNotFoundException:
        print("[aws] creating function")
        for attempt in range(5):
            try:
                lam.create_function(FunctionName=NAME, Runtime="python3.12", Role=role, Handler="lambda_app.handler",
                                    Code=loc, Timeout=90, MemorySize=1024, Environment=env,
                                    Description="Nalam AI - Tamil-first health helper (Strands + Amazon Bedrock)")
                break
            except lam.exceptions.InvalidParameterValueException as e:  # role not visible to Lambda yet
                if attempt == 4:
                    raise
                print("[aws] role not ready yet, retrying in 10 s:", str(e)[:80])
                time.sleep(10)
    wait_ready(lam)
    try:
        lam.put_function_concurrency(FunctionName=NAME, ReservedConcurrentExecutions=5)
    except Exception as e:  # noqa: BLE001  small new accounts cannot reserve concurrency; the per-device limit still applies
        print("[aws] (skip concurrency cap:", type(e).__name__ + ")")
    try:
        url = lam.get_function_url_config(FunctionName=NAME)["FunctionUrl"]
    except lam.exceptions.ResourceNotFoundException:
        url = lam.create_function_url_config(FunctionName=NAME, AuthType="NONE")["FunctionUrl"]
    for sid, action, extra in (("public-url", "lambda:InvokeFunctionUrl", {"FunctionUrlAuthType": "NONE"}),
                               ("public-url-invoke", "lambda:InvokeFunction", {"InvokedViaFunctionUrl": True})):
        try:
            lam.add_permission(FunctionName=NAME, StatementId=sid, Action=action, Principal="*", **extra)
        except lam.exceptions.ResourceConflictException:
            pass
        except Exception as e:  # noqa: BLE001  older botocore without InvokedViaFunctionUrl
            print("[aws] (permission", sid, "skipped:", type(e).__name__ + ")")
    OUT.write_text(json.dumps({"url": url, "function": NAME, "region": REGION}, indent=2) + "\n")
    print(f"\n[aws] live: {url}\n(first open can take ~10 s while it starts)")


def delete() -> None:
    sess = session()
    lam, iam = sess.client("lambda"), sess.client("iam")
    for fn in (lambda: lam.delete_function_url_config(FunctionName=NAME), lambda: lam.delete_function(FunctionName=NAME)):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print("[aws] skip:", type(e).__name__)
    for fn in (lambda: iam.delete_role_policy(RoleName=ROLE, PolicyName="bedrock-only"),
               lambda: iam.detach_role_policy(RoleName=ROLE, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"),
               lambda: iam.delete_role(RoleName=ROLE)):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print("[aws] skip:", type(e).__name__)
    try:
        acct = sess.client("sts").get_caller_identity()["Account"]
        b = sess.resource("s3").Bucket(f"nalam-web-{acct}-{REGION}")
        b.objects.all().delete()  # code package, family data and photos
        b.delete()
    except Exception as e:  # noqa: BLE001
        print("[aws] skip bucket:", type(e).__name__)
    OUT.unlink(missing_ok=True)
    print("[aws] deleted")


def logs() -> None:
    """Print the last errors from the app's CloudWatch log (to find why something failed on AWS)."""
    cw = session().client("logs")
    group = f"/aws/lambda/{NAME}"
    streams = cw.describe_log_streams(logGroupName=group, orderBy="LastEventTime", descending=True, limit=3)["logStreams"]
    for st in reversed(streams):
        for e in cw.get_log_events(logGroupName=group, logStreamName=st["logStreamName"], limit=200, startFromHead=False)["events"]:
            msg = e["message"].rstrip()
            if not msg.startswith(("START", "END", "REPORT")):
                print(msg[:400])


if __name__ == "__main__":
    if "--delete" in sys.argv:
        delete()
    elif "--logs" in sys.argv:
        logs()
    else:
        deploy()
