@echo off
rem Put Nalam AI on AWS (Lambda + public link). Add --delete to remove it.
set AWS_PROFILE=nalam
set AWS_REGION=us-east-1
set PYTHONIOENCODING=utf-8
"%USERPROFILE%\.strands-ship\venv\Scripts\python.exe" deploy\deploy_aws.py %*
