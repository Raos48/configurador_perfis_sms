"""
Configurador de Perfil SAGGESTAO — Script Standalone

Executa a configuração completa de perfil de um servidor:
- Serviços na tabela principal (Competência, AtribResp, Transferência)
- Competências por unidade no modal (AtivarMiExer, BloquerAlteracoes)
- Confirmação final

Uso:
    python configurar_perfil.py
"""

import sys
import time
import re
import logging

import urllib3
from playwright.sync_api import sync_playwright, Page, Error as PlaywrightError

from auth import SaggestaoAuth
from colored_logger import setup_colored_logging
from config import (
    SAGGESTAO_CONSULTATION_URL as CONSULTATION_URL,
    BROWSER_HEADLESS,
    PLAYWRIGHT_DEFAULT_TIMEOUT as DEFAULT_TIMEOUT,
    MAX_RETRIES,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Valores padrão fixos da configuração de perfil
DEFAULTS = {
    "atrib_resp":          "Não",
    "trasf":               "Não",
    "ativar_mi_exer":      "Sim",
    "bloquear_alteracoes": "Não",
    "resetar_todos_sv":    "Não",
    "area_meio":           "Não",
}

setup_colored_logging(log_level=logging.INFO)
logger = logging.getLogger("ConfiguradorPerfil")


def coletar_dados_prompt() -> tuple[str, str, list[str]]:
    """Solicita ao usuário SIAPE, unidade e códigos SV via prompt."""
    print("\n" + "="*60)
    print("  CONFIGURADOR DE PERFIL SAGGESTAO")
    print("="*60)

    siape = input("\nSIAPE do servidor: ").strip()
    if not siape:
        print("SIAPE não pode ser vazio.")
        sys.exit(1)

    unidade = input("Código da Unidade: ").strip()
    if not unidade:
        print("Código da Unidade não pode ser vazio.")
        sys.exit(1)

    print("\nCódigos SV (digite um por linha; linha vazia para encerrar):")
    codigos_sv = []
    while True:
        cod = input("  Código SV: ").strip()
        if not cod:
            break
        codigos_sv.append(cod)

    if not codigos_sv:
        print("AVISO: Nenhum código SV informado. Prosseguindo sem configurar serviços.")

    print(f"\nDados coletados:")
    print(f"  SIAPE:    {siape}")
    print(f"  Unidade:  {unidade}")
    print(f"  Cód. SVs: {codigos_sv or '(nenhum)'}")
    print(f"\nConfigurações padrão:")
    for k, v in DEFAULTS.items():
        print(f"  {k}: {v}")
    print()

    confirmar = input("Confirmar e iniciar? (s/N): ").strip().lower()
    if confirmar != 's':
        print("Operação cancelada.")
        sys.exit(0)

    return siape, unidade, codigos_sv


if __name__ == "__main__":
    siape, unidade, codigos_sv = coletar_dados_prompt()
    print("Estrutura base OK — implementação em andamento.")
