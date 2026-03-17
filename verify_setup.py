"""
Script de verificação de ambiente para o RPA.
Valida se as configurações e dependências estão corretas antes da execução.
"""

import sys
import os
import importlib.util

def check_file_exists(filepath, description):
    exists = os.path.exists(filepath)
    print(f"[{'OK' if exists else 'FAIL'}] {description} ({filepath})")
    return exists

def check_module_installed(module_name):
    spec = importlib.util.find_spec(module_name)
    installed = spec is not None
    print(f"[{'OK' if installed else 'FAIL'}] Módulo Python: {module_name}")
    return installed

def verify_setup():
    print("=== Verificação de Ambiente RPA ===")
    
    # 1. Verificar arquivos críticos
    files_ok = True
    files_ok &= check_file_exists(".env", "Arquivo de configuração .env")
    files_ok &= check_file_exists("servico_rpa.py", "Script principal")
    files_ok &= check_file_exists("auth.py", "Módulo de autenticação")
    files_ok &= check_file_exists("metrics.py", "Módulo de métricas")
    
    if not files_ok:
        print("\n[ERRO] Arquivos essenciais faltando.")
        if not os.path.exists(".env") and os.path.exists(".env.example"):
            print("DICA: Copie .env.example para .env e configure suas credenciais.")
    
    # 2. Verificar dependências
    modules_ok = True
    modules_ok &= check_module_installed("dotenv")
    modules_ok &= check_module_installed("tenacity")
    modules_ok &= check_module_installed("playwright")
    modules_ok &= check_module_installed("requests")
    modules_ok &= check_module_installed("colorama")

    if not modules_ok:
        print("\n[ERRO] Dependências faltando. Execute: pip install -r requirements.txt")

    # 3. Verificar carregamento de configurações
    print("\n--- Teste de Carregamento de Configurações ---")
    try:
        from config import SIGA_API_URL, SIGA_EMAIL, POLLING_INTERVAL
        print(f"[OK] Configuração carregada com sucesso.")
        print(f"     API URL: {SIGA_API_URL}")
        print(f"     Email: {SIGA_EMAIL}")
        print(f"     Polling Interval: {POLLING_INTERVAL}s")
    except ImportError as e:
        print(f"[FAIL] Erro ao importar config.py: {e}")
    except ValueError as e:
        print(f"[FAIL] Erro de validação em config.py: {e}")
        print("DICA: Verifique se todas as variáveis obrigatórias estão no .env")
    except Exception as e:
        print(f"[FAIL] Erro inesperado ao carregar config: {e}")

    print("\n=== Fim da Verificação ===")

if __name__ == "__main__":
    verify_setup()
