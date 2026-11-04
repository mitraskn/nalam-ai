@echo off
rem Runs the STRANDS-SHIP kit commands (ss cases / ss measure ...) on Windows.
set AWS_PROFILE=nalam
set AWS_REGION=us-east-1
set PYTHONIOENCODING=utf-8
"%USERPROFILE%\.strands-ship\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, r'%USERPROFILE%\.strands-ship\kit'); from ship_kit.cli import main; sys.exit(main())" %*
