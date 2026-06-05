@echo off
cd /d "%~dp0"
".venv-paddle-gpu\Scripts\python.exe" paddleocr_pdf_test.py --device gpu
pause
