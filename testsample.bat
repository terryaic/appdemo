@echo off
setlocal
call "%~dp0kit\kit.exe" "%%~dp0apps/sample.kit" --/persistent/xr/profile/tabletar/enabled=false %*
