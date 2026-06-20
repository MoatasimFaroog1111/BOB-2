@echo off
title GuardianAI Backend
echo Starting FastAPI Backend...
cd /d "%~dp0backend"
.\venv\Scripts\python.exe run_backend.py
pause
