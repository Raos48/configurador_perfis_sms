@echo off
:a
"C:\Program Files\Java\jdk-20\bin\java.exe" -jar "F:\PYTHON\Bloqueador de Perfis SAGGESTAO\Servidor\Autenticacao.jar" -Djdk.internal.httpclient.disableHostnameVerification=true 48000
timeout /t 3 /nobreak
goto a