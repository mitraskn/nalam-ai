"""Make the Nalam AI demo video from a LIVE run of the deployed app. No screen recorder, no editing.

    .\\make_video            (Windows)   or   python tests/make_video.py [URL]

A real browser opens the live app, does each step while an English voice-over (gTTS) explains it,
and the result is written to results/demo.mp4 (1280x720, with sound). Every answer on screen is real.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = "https://sio5kbdhxqtguxay6f3xshiehm0metgc.lambda-url.ap-southeast-2.on.aws/"
URL = sys.argv[1] if len(sys.argv) > 1 else LIVE
OUT = ROOT / "results"
TMP = OUT / "_video"
SAMPLES = ROOT / "samples"
REPO = "github.com/mitraskn/nalam-ai"


def need(mod: str, pkg: str) -> None:
    try:
        __import__(mod)
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg], check=True)


for m, p in (("gtts", "gTTS"), ("mutagen", "mutagen"), ("imageio_ffmpeg", "imageio-ffmpeg"), ("playwright", "playwright")):
    need(m, p)

from gtts import gTTS                      # noqa: E402
from mutagen.mp3 import MP3                # noqa: E402
import imageio_ffmpeg                      # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

M = json.loads((OUT / "measure.json").read_text(encoding="utf-8"))
A, B = M["agent"]["overall"], M["baseline"]["overall"]
TA_A, TA_B = M["agent"]["by_language"]["ta"], M["baseline"]["by_language"]["ta"]

SAY = {
    "title": "Nalam AI. Health help, in Paati's own language.",
    "story": "My grandmother in Coimbatore gets her blood reports and prescriptions in English. She can't read them, "
             "so she waits for someone in the family to explain. Nalam AI explains them in Tamil or English, by text "
             "and by voice. Setup takes a few seconds: a family member for SOS, and who the app is for.",
    "report": "Upload a photo of the blood report. Amazon Nova only reads the values. Plain Python then compares each "
              "value with the range printed on that report, so High, Low and Normal are decided by code, "
              "with a source link for every test.",
    "rx": "A prescription works the same way. It explains what each medicine is for. How often to take it comes "
          "only from the prescription, never from the AI.",
    "ask": "She can ask in Tanglish too. Here she says she took Metformin, but she is vomiting. "
           "The app answers, and gently says when to see a doctor.",
    "elder": "For elders, there is a big-text Tamil mode with five simple tiles.",
    "refuse": "Now the hard cases. My sugar is normal now, can I stop the tablet? Nalam AI never changes a dose. "
              "It says to ask the doctor or the pharmacist.",
    "sos": "Amma has chest pain and can't breathe. A safety check written in plain code runs before any AI, "
           "so this goes straight to 108 and the family SOS buttons.",
    "measured": "It is built with the Strands Agents SDK: a planner and critic graph, with a hook that stops the "
                "agents on any red flag. We tested it on thirty nine signed-off cases against a single-prompt "
                "agent on the same model. Nalam AI handed off every danger case and gave no unsafe answers. "
                "In Tamil, the single-prompt agent missed one danger case in four, and gave two unsafe answers.",
    "end": "All medicine information is checked against official sources: MedlinePlus, NHS, EMA and WHO. "
           "Built with Kiro. The code is on GitHub.",
}

OVERLAY = r"""
(() => {
 if (document.getElementById('vidL')) return;
 const css = document.createElement('style');
 css.textContent = `
 #vidL,#vidR{position:fixed;top:0;bottom:0;width:390px;z-index:9999;pointer-events:none;display:flex;flex-direction:column;
   justify-content:center;padding:36px;box-sizing:border-box;font-family:"Segoe UI",system-ui,sans-serif}
 #vidL{left:0;background:#fff7ed}#vidR{right:0;background:#fff7ed}
 #vidL .k{font-size:15px;letter-spacing:.08em;color:#c2410c;font-weight:700;text-transform:uppercase}
 #vidL h2{font-size:30px;line-height:1.2;margin:10px 0 14px;color:#1f2937}
 #vidL p{font-size:19px;line-height:1.45;color:#374151;margin:0}
 #vidR .pill{background:#fff;border:2px solid #fdba74;border-radius:16px;padding:14px 16px;margin:8px 0;font-size:17px;color:#1f2937;line-height:1.35}
 #vidR .pill b{color:#c2410c}
 #vidCard{position:fixed;inset:0;z-index:10000;background:#fff7ed;display:none;flex-direction:column;align-items:center;
   justify-content:center;text-align:center;font-family:"Segoe UI","Nirmala UI",system-ui,sans-serif;padding:40px}
 #vidCard h1{font-size:54px;margin:0 0 6px;color:#c2410c}#vidCard h3{font-size:26px;margin:0 0 22px;color:#1f2937;font-weight:600}
 #vidCard p{font-size:22px;margin:7px 0;color:#374151;max-width:1050px;line-height:1.4}
 #vidCard table{border-collapse:collapse;margin:10px 0 18px;font-size:21px}
 #vidCard td,#vidCard th{border:1px solid #fdba74;padding:9px 18px;background:#fff}#vidCard th{background:#ffedd5}
 #vidCard .g{color:#15803d;font-weight:800}#vidCard .r{color:#b91c1c;font-weight:700}`;
 document.head.appendChild(css);
 for (const id of ['vidL','vidR','vidCard']) { const d=document.createElement('div'); d.id=id; document.body.appendChild(d); }
})()"""


def tts(key: str) -> tuple[Path, float]:
    f = TMP / f"{key}.mp3"
    if not f.exists():
        gTTS(SAY[key], lang="en", tld="co.in").save(str(f))
    return f, MP3(str(f)).info.length


def main() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    clips = {k: tts(k) for k in SAY}
    print("voice ready:", round(sum(d for _, d in clips.values())), "s of narration")
    cues: list[tuple[str, float]] = []

    with sync_playwright() as pw:
        try:
            br = pw.chromium.launch()
        except Exception:
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            br = pw.chromium.launch()
        # wake the Lambda up so the video doesn't show a cold start
        w = br.new_page(); w.goto(URL); w.wait_for_timeout(1500); w.close()

        ctx = br.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(TMP / "raw"),
                             record_video_size={"width": 1280, "height": 720})
        pg = ctx.new_page()
        t0 = time.time()
        pg.on("dialog", lambda d: d.accept())
        pg.goto(URL)
        pg.wait_for_selector("#wFamName")
        pg.evaluate(OVERLAY)
        W = pg.wait_for_timeout

        def side(kicker: str, title: str, text: str, pills: list[str] | None = None) -> None:
            pg.evaluate("""([k,t,x,p]) => {document.getElementById('vidCard').style.display='none';
              document.getElementById('vidL').innerHTML=`<div class="k">${k}</div><h2>${t}</h2><p>${x}</p>`;
              document.getElementById('vidR').innerHTML=p.map(s=>`<div class="pill">${s}</div>`).join('')}""",
                        [kicker, title, text, pills or []])

        def card(html: str) -> None:
            pg.evaluate("h => {const c=document.getElementById('vidCard');c.innerHTML=h;c.style.display='flex'}", html)

        def scene(key: str):
            start = time.time()
            cues.append((key, start - t0))
            return lambda: W(max(300, int((clips[key][1] + 0.6 - (time.time() - start)) * 1000)))

        def type_slow(sel: str, text: str) -> None:
            pg.click(sel); pg.fill(sel, ""); pg.type(sel, text, delay=35)

        def ask(q: str, send: str, wait_ms: int = 1500) -> None:
            before = pg.locator(".chat .bot").count()
            pg.click("#askIn"); pg.fill("#askIn", "")
            pg.type("#askIn", q, delay=30)
            pg.click(f".askbar >> text={send}")
            pg.wait_for_function("n => document.querySelectorAll('.chat .bot').length > n",
                                 arg=before, timeout=45000)
            W(wait_ms)
            pg.evaluate("() => {const b=document.querySelectorAll('.chat .bot'); b[b.length-1].scrollIntoView({block:'center', behavior:'smooth'})}")

        def wait_out(el: str) -> None:
            pg.wait_for_function("id => {const o=document.getElementById(id); return o && o.innerText.length > 40 && !o.querySelector('.spinner')}",
                                 arg=el, timeout=90000)

        def scroll(px: int) -> None:
            pg.evaluate("y => window.scrollBy({top: y, behavior: 'smooth'})", px)

        # 0. title
        done = scene("title")
        card("<h1>Nalam AI · நலம் AI</h1><h3>A Tamil-first health helper for families</h3>"
             "<p>Live run of the deployed app on AWS Lambda + Amazon Bedrock. Every answer on screen is real.</p>")
        done()

        # 1. story + setup
        done = scene("story")
        side("The problem", "Paati can't read her own reports",
             "Blood reports and prescriptions come in English. Nalam AI explains them in Tamil or English, by text and voice.",
             ["<b>Home page</b>: language, mode, family SOS contact, who the app is for"])
        W(1500)
        pg.click("text=English"); W(300); pg.click("text=Normal mode"); W(400)
        type_slow("#wFamName", "Mitra"); type_slow("#wFamPhone", "98765 43210"); type_slow("#wPerson", "Paati")
        W(600); pg.click("text=Continue →"); pg.wait_for_selector(".hello"); W(800)
        done()

        # 2. report
        done = scene("report")
        side("Blood report", "Photo in, plain words out",
             "Amazon Nova reads the values. Python compares each one with the range printed on the report.",
             ["<b>High / Low / Normal</b> decided by code", "<b>42 tests</b> explained, each with a MedlinePlus source",
              "Questions to ask the doctor"])
        pg.click("text=Understand my report"); W(900)
        with pg.expect_file_chooser() as fc:
            pg.click("#main button.primary")
        fc.value.set_files(str(SAMPLES / "sample_report_1_with_ranges.png"))
        wait_out("repOut")
        W(1200)
        for _ in range(4):
            scroll(260); W(700)
        done()

        # 3. prescription
        done = scene("rx")
        side("Prescription", "What each medicine is for",
             "How often to take it comes only from the prescription. Unclear handwriting is marked 'not sure'.",
             ["<b>BD</b> = 2 times a day", "<b>TDS</b> = 3 times a day", "Save to the family's medicine list"])
        pg.click("#backBtn"); W(600)
        pg.click("text=Read prescription"); W(800)
        with pg.expect_file_chooser() as fc:
            pg.click("#main button.primary")
        fc.value.set_files(str(SAMPLES / "sample_prescription_printed.png"))
        wait_out("rxOut")
        W(1000); scroll(300); W(800)
        done()

        # 4. Tanglish question with a warning sign
        done = scene("ask")
        side("Ask anything", "Tamil, English or Tanglish",
             "A warning sign inside a normal question gets a gentle note, and the conversation continues.",
             ["Typed or spoken", "Every answer can be read aloud"])
        pg.click("#backBtn"); W(600)
        pg.click("text=Ask a question"); W(700)
        ask("Metformin sapten, aana vaanthi varuthu", "Send", 2000)
        done()

        # 5. Elder mode in Tamil
        done = scene("elder")
        side("Elder mode", "Big text, Tamil, five tiles", "Built for Paati: voice first, nothing to read in English.")
        pg.click("#homeBtn"); W(700)
        pg.click("text=தமிழ்"); W(400); pg.click("text=👵 பெரியவர் முறை"); W(500)
        pg.click("text=தொடரவும் →"); pg.wait_for_selector(".hello"); W(1200)
        done()

        # 6. dose question -> refused
        done = scene("refuse")
        side("Safety", "It never changes a dose",
             "“My sugar is normal now, can I stop the tablet?”",
             ["Checked by <b>code</b>, before any AI", "Answer: ask the doctor or pharmacist"])
        pg.click("text=கேள்வி கேளுங்கள்"); W(700)
        ask("சுகர் சரியாயிடுச்சு, மாத்திரையை நிறுத்தலாமா?", "அனுப்பு", 1500)
        done()

        # 7. emergency -> 108 + SOS
        done = scene("sos")
        side("Emergency", "Straight to 108 and family",
             "“Amma has chest pain and can't breathe.”",
             ["Danger signs in Tamil, English and Tanglish", "<b>SOS</b>: call family · call 108 · share location"])
        ask("அம்மாவுக்கு நெஞ்சு வலிக்குது, மூச்சு விட முடியல", "அனுப்பு", 1000)
        done()

        # 8. measured
        done = scene("measured")
        pc = lambda x: f"{x:.0%}"
        card("<h1 style='font-size:40px'>Measured, not claimed</h1>"
             f"<p>{A['cases']} human-labelled, signed-off cases ({M['cases']['emergency']} hand-off, {M['cases']['ta']} in Tamil). "
             "Same model for both. Baseline = one prompt, same guidance, no tools, graph, critic or hook.</p>"
             "<table><tr><th></th><th>Nalam AI (Strands graph + hook)</th><th>Single-prompt agent</th></tr>"
             f"<tr><td>Danger cases handed off</td><td class=g>{pc(A['emergency_recall'])}</td><td>{pc(B['emergency_recall'])}</td></tr>"
             f"<tr><td>…in Tamil</td><td class=g>{pc(TA_A['emergency_recall'])}</td><td class=r>{pc(TA_B['emergency_recall'])}</td></tr>"
             f"<tr><td>Unsafe answers</td><td class=g>{A['unsafe']}</td><td class=r>{B['unsafe']}</td></tr>"
             f"<tr><td>Goal success (Strands Evals)</td><td class=g>{A['goal_success']}</td><td>{B['goal_success']}</td></tr>"
             f"<tr><td>Median latency</td><td class=g>{A['latency_p50_ms']/1000:.1f} s</td><td>{B['latency_p50_ms']/1000:.1f} s</td></tr></table>"
             "<p>Strands Agents SDK: planner ⇄ critic graph · RedFlagGate hook · Amazon Nova on Bedrock</p>")
        done()

        # 9. end
        done = scene("end")
        card("<h1>Nalam AI · நலம் AI</h1>"
             "<p>Medicine information checked against official sources:<br><b>MedlinePlus · NHS · EMA · WHO</b></p>"
             f"<p style='margin-top:22px'>Code: <b>{REPO}</b></p><p>Built with Kiro and the Strands Agents SDK</p>"
             "<p style='color:#c2410c'>#strands-agents #health</p>")
        done(); W(1200)

        video = pg.video
        ctx.close(); br.close()
        raw = Path(video.path())
    total = time.time() - t0

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-loglevel", "error", "-i", str(raw)]
    for k, _ in cues:
        cmd += ["-i", str(clips[k][0])]
    parts = "".join(f"[{i + 1}:a]adelay={int(t * 1000)}|{int(t * 1000)}[a{i}];" for i, (_, t) in enumerate(cues))
    mix = "".join(f"[a{i}]" for i in range(len(cues))) + f"amix=inputs={len(cues)}:normalize=0[a]"
    out = OUT / "demo.mp4"
    cmd += ["-filter_complex", parts + mix, "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    (OUT / "video_cues.json").write_text(json.dumps({"cues": cues, "seconds": round(total, 1)}, indent=1))
    print(f"\nDONE: {out}  ({total:.0f} s, {'under' if total < 180 else 'OVER'} 3 minutes)")


if __name__ == "__main__":
    main()
