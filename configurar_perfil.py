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


def iniciar_sessao(playwright_instance):
    """
    Cria browser autenticado e navega para a página de consulta.
    Retorna (browser, context, page) prontos para uso.
    Lida com seleção de domínio caso apareça após o login.
    """
    logger.info("Iniciando browser e autenticando...")

    browser = playwright_instance.chromium.launch(headless=BROWSER_HEADLESS)
    context = SaggestaoAuth.configurar_contexto(browser)
    page = context.new_page()
    page.set_default_timeout(DEFAULT_TIMEOUT)

    logger.info("Navegando para página de consulta...")
    page.goto(CONSULTATION_URL, wait_until="domcontentloaded", timeout=120000)

    # Seleção de domínio (aparece em alguns ambientes)
    time.sleep(2)
    domain_selector = page.locator("select#domains")
    if domain_selector.count() > 0:
        logger.info("Página de seleção de domínio detectada. Selecionando UO:01.001.PRES...")
        domain_selector.select_option("UO:01.001.PRES")
        time.sleep(1)
        page.get_by_role("button", name="Enviar").click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)

    # Aguarda campo SIAPE para confirmar login
    logger.info("Aguardando confirmação de login...")
    page.wait_for_selector('input[name="form\\:idMskSiape"]', state="visible", timeout=120000)
    logger.info("Login confirmado.")

    return browser, context, page


def executar_configuracao(page: Page, siape: str, unidade: str, codigos_sv: list[str]) -> bool:
    """
    Orquestra todas as etapas de configuração de perfil.
    Retorna True em sucesso, False em falha.
    """
    logger.info(f"Iniciando configuração: SIAPE={siape} | Unidade={unidade} | SVs={codigos_sv}")
    # TODO: implementado nas tasks seguintes
    return False


def main():
    siape, unidade, codigos_sv = coletar_dados_prompt()

    with sync_playwright() as pw:
        browser, context, page = iniciar_sessao(pw)
        try:
            sucesso = executar_configuracao(page, siape, unidade, codigos_sv)
            if sucesso:
                logger.info("CONFIGURAÇÃO CONCLUÍDA COM SUCESSO.")
            else:
                logger.error("CONFIGURAÇÃO FALHOU.")
                sys.exit(1)
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
