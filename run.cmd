@echo off
set AWS_PROFILE=nalam
set AWS_REGION=us-east-1
set PYTHONIOENCODING=utf-8
"%USERPROFILE%\.strands-ship\venv\Scripts\python.exe" -m agent.app %*
