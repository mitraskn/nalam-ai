@echo off
rem Makes results\demo.mp4 from a live run of the deployed app (about 3 minutes).
set PYTHONIOENCODING=utf-8
"%USERPROFILE%\.strands-ship\venv\Scripts\python.exe" tests\make_video.py %*
