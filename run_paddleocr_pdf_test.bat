@echo off
cd /d "%~dp0"
".venv-paddle\Scripts\python.exe" paddleocr_pdf_test.py --device cpu
pause
