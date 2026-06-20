@echo off
title GuardianAI Frontend
echo Starting Next.js Frontend...
cd /d "%~dp0frontend"
set NODE_OPTIONS=--max-old-space-size=4096
npm run dev
pause

