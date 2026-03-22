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


def _set_checkbox(page: Page, checkbox_locator, desired_state: bool, label: str = "checkbox") -> bool:
    """Define o estado de um checkbox. Retorna True se bem-sucedido."""
    try:
        for _ in range(3):
            if checkbox_locator.count() > 0 and checkbox_locator.first.is_visible():
                current = checkbox_locator.first.is_checked()
                if current == desired_state:
                    return True
                checkbox_locator.first.click()
                page.wait_for_timeout(500)
                if checkbox_locator.first.is_checked() == desired_state:
                    return True
            time.sleep(1)
        logger.warning(f"Não foi possível definir {label} para {desired_state}")
        return False
    except Exception as e:
        logger.warning(f"Erro ao ajustar {label}: {e}")
        return False


def configurar_servicos_tabela_principal(
    page: Page, codigos_sv: list[str],
    atrib_resp: str = "Não", trasf: str = "Não"
) -> None:
    """
    Para cada código SV na tabela principal:
      - Digita o código no campo de filtro
      - Marca Competência (sempre True)
      - Define AtribuiçãoResp e Transferência conforme parâmetros
    Erros por código são logados mas não interrompem os demais.
    """
    if not codigos_sv:
        logger.info("Nenhum código SV para configurar na tabela principal.")
        return

    input_selector = '[id="form\\:tabelaServico\\:codigoServico"]'

    for cod in codigos_sv:
        logger.info(f"Configurando código SV {cod} na tabela principal...")
        try:
            # Encontra e limpa o campo
            campo = page.locator(input_selector)
            if campo.count() == 0:
                logger.warning(f"Campo de código SV não encontrado para {cod}. Pulando.")
                continue

            campo.first.focus()
            campo.first.click(click_count=3)
            campo.first.press("Backspace")
            campo.first.clear()
            campo.first.type(str(cod), delay=100)
            page.wait_for_timeout(2000)

            # Aguarda resultado: célula com o código OU "Nenhum registro"
            celula_sv = page.get_by_role("gridcell", name=str(cod), exact=True).filter(visible=True)
            msg_vazio = page.get_by_text("Nenhum registro encontrado.")

            try:
                celula_sv.or_(msg_vazio).first.wait_for(state="visible", timeout=10000)
            except Exception:
                logger.warning(f"Timeout aguardando resultado do filtro para {cod}. Pulando.")
                continue

            if not celula_sv.is_visible():
                logger.warning(f"Código SV {cod} não encontrado na tabela principal. Pulando.")
                continue

            # Encontra a linha do código
            linha = celula_sv.locator("xpath=ancestor::tr")

            # Checkbox Competência (sempre marcar)
            cb_comp = linha.locator("input[name*='selecionarDeselecionarCompetencia']")
            _set_checkbox(page, cb_comp, True, f"Competencia[{cod}]")

            # Checkbox AtribuiçãoResp
            cb_atrib = linha.locator("input[name*='selecionarDeselecionarAtribuicao']")
            _set_checkbox(page, cb_atrib, atrib_resp == "Sim", f"AtribResp[{cod}]")

            # Checkbox Transferência
            cb_trasf = linha.locator("input[name*='selecionarDeselecionarTransferencia']")
            _set_checkbox(page, cb_trasf, trasf == "Sim", f"Trasf[{cod}]")

            logger.info(f"Código SV {cod} configurado na tabela principal.")

        except Exception as e:
            logger.warning(f"Erro ao processar código SV {cod}: {e}")
            continue


def abrir_modal_competencias_unidade(page: Page, unidade: str) -> bool:
    """
    Na tabela de unidades, encontra a unidade alvo:
      1. Marca o checkbox GET
      2. Clica no botão lápis para abrir o modal de competências por unidade
    Retorna True se o modal abrir com sucesso.
    Estratégia de navegação baseada em saggestao_automation_referencia.py.
    """
    paginator_selector = '[id="form\\:tabelaUnidades_paginator_bottom"]'
    logger.info(f"Buscando unidade {unidade} na tabela de unidades...")

    # Garante início na página 1
    try:
        btn_first = page.locator(f"{paginator_selector} a.ui-paginator-first:not(.ui-state-disabled)")
        if btn_first.count() > 0 and btn_first.is_visible():
            btn_first.first.click()
            logger.info("Tabela de unidades resetada para a página 1.")
            page.wait_for_timeout(3000)
        else:
            logger.info("Tabela já está na página 1 ou não há paginação.")
    except Exception as e:
        logger.warning(f"Não foi possível clicar em 'Primeira Página': {e}")

    page_num = 1
    while True:
        logger.info(f"Procurando unidade '{unidade}' na página {page_num}...")

        # Espera inteligente: aguarda a primeira linha estar visível
        try:
            page.locator("#form\\:tabelaUnidades_data tr").first.wait_for(state="visible", timeout=10000)
        except PlaywrightError:
            logger.error(f"Nenhuma linha encontrada na tabela na página {page_num}.")
            return False

        linhas = page.locator("#form\\:tabelaUnidades_data tr")
        row_count = linhas.count()

        for i in range(row_count):
            linha = linhas.nth(i)
            logger.debug(f"Analisando linha {i+1}/{row_count}...")
            try:
                celula_codigo = linha.locator("td:nth-child(2)")
                if celula_codigo.count() == 0:
                    continue

                texto_celula = celula_codigo.first.text_content(timeout=2000) or ""
                logger.debug(f"Texto bruto da célula: '{texto_celula.strip()}'")

                # Extrai código numérico via regex (igual ao script de referência)
                match = re.search(r'(\d+)', texto_celula)
                if not match:
                    logger.debug("Regex não encontrou código numérico na célula.")
                    continue

                codigo_extraido = match.group(1)
                logger.debug(f"Código extraído: '{codigo_extraido}' | Procurado: '{unidade}'")

                if codigo_extraido != str(unidade):
                    continue

                logger.info(f"Unidade {unidade} encontrada na linha {i+1}, página {page_num}.")

                # Marca checkbox GET
                cb_get = linha.locator('[id$="selecionarDeselecionarGet"]')
                if cb_get.count() > 0 and cb_get.is_visible():
                    cb_get.check()
                    logger.info("Checkbox GET marcado.")
                else:
                    logger.warning("Checkbox GET não encontrado ou não visível.")

                # Clica no botão lápis (abre modal de competências)
                btn_modal = linha.get_by_label("Competências do profissional por unidade").or_(
                    linha.locator("a.ico-pencil")
                )

                button_clicked = False
                for tentativa in range(1, 4):
                    logger.debug(f"Tentativa {tentativa}/3 para clicar no botão lápis...")
                    if btn_modal.count() > 0 and btn_modal.first.is_visible():
                        try:
                            btn_modal.first.click()
                            logger.info("Botão lápis clicado com sucesso.")
                            button_clicked = True
                            break
                        except Exception as e_click:
                            logger.debug(f"Erro ao clicar na tentativa {tentativa}: {e_click}")
                    if tentativa < 3:
                        page.wait_for_timeout(1000)

                if button_clicked:
                    page.wait_for_timeout(1000)
                    return True
                else:
                    logger.error(f"Botão lápis não foi clicado após 3 tentativas.")
                    return False

            except Exception as e:
                logger.warning(f"Erro ao processar linha {i+1}: {e}")
                continue

        # Próxima página
        try:
            btn_next = page.locator(f"{paginator_selector} a.ui-paginator-next:not(.ui-state-disabled)")
            if btn_next.count() > 0:
                logger.info(f"Unidade não encontrada na página {page_num}. Indo para próxima página...")
                btn_next.first.click()
                page.wait_for_timeout(3000)
                page_num += 1
            else:
                logger.error(f"Unidade '{unidade}' não encontrada em nenhuma página da tabela.")
                return False
        except Exception as e:
            logger.error(f"Erro ao navegar para próxima página: {e}")
            return False


def configurar_modal_competencias(
    page: Page, codigos_sv: list[str],
    ativar_mi_exer: str = "Sim",
    bloquear_alteracoes: str = "Não"
) -> bool:
    """
    Dentro do modal de competências por unidade:
      1. Configura BloquerAlteracoes (radio Sim/Não)
      2. Para cada CódigoSV: digita no campo modal, ajusta checkbox AtivarMiExer
      3. Clica Confirmar do modal
    Retorna True se o modal for confirmado com sucesso.
    """
    modal_prefix = "cmpModalCompetenciaServicoLocal:formPesquisaCompetencias"

    # 1. Configurar BloquerAlteracoes
    logger.info(f"Configurando BloquerAlteracoes = {bloquear_alteracoes}...")
    try:
        if bloquear_alteracoes == "Sim":
            radio = page.locator("input[id*='bloquearAlteracaoExercicio:1']")
        else:
            radio = page.locator("input[id*='bloquearAlteracaoExercicio:0']")

        if radio.count() > 0:
            if not radio.first.is_checked():
                radio.first.click()
                time.sleep(1)
            logger.info(f"BloquerAlteracoes configurado para {bloquear_alteracoes}.")
        else:
            logger.warning("Radio BloquerAlteracoes não encontrado no modal.")
    except Exception as e:
        logger.warning(f"Erro ao configurar BloquerAlteracoes: {e}")

    # 2. Processar cada CódigoSV no modal
    input_modal_selector = (
        f'[id="{modal_prefix}\\:tabelaServicoModal\\:codigoModalServico"]'
    )
    msg_sem_registro = "xpath=//div[@id='cmpModalCompetenciaServicoLocal:formPesquisaCompetencias:tabelaServicoModal']//td[contains(text(),'Nenhum registro encontrado')]"

    for cod in codigos_sv:
        logger.info(f"Configurando código SV {cod} no modal...")
        try:
            campo_modal = page.locator(input_modal_selector)
            if campo_modal.count() == 0:
                logger.warning(f"Campo do modal não encontrado para código {cod}. Pulando.")
                continue

            campo_modal.first.clear()
            campo_modal.first.type(str(cod), delay=50)
            page.wait_for_timeout(2000)

            # Usa seletor direto que inclui o container do modal para evitar
            # match em outras tabelas do DOM (baseado no ID hardcoded do script de referência)
            cb_direto = page.locator('[id*="tabelaServicoModal:0:selecionarDeselecionarCompetencia"]')
            if cb_direto.count() > 0 and cb_direto.first.is_visible(timeout=3000):
                desired = (ativar_mi_exer == "Sim")
                _set_checkbox(page, cb_direto, desired, f"AtivarMiExer[{cod}]")
                time.sleep(1)
            else:
                # Checkbox não apareceu — verifica se é "nenhum registro" ou erro inesperado
                sem_reg = page.locator(msg_sem_registro)
                if sem_reg.count() > 0 and sem_reg.first.is_visible(timeout=2000):
                    logger.warning(f"Código SV {cod} não encontrado no modal. Pulando.")
                else:
                    logger.warning(f"Estado inesperado no modal para código {cod}. Pulando.")

        except Exception as e:
            logger.warning(f"Erro ao processar código {cod} no modal: {e}")
            continue

    # 3. Confirmar modal
    logger.info("Confirmando modal de competências...")
    btn_confirmar_modal = page.locator(
        f'[id="{modal_prefix}\\:botaoConfirmarModalCompetenciaServicoLocal"]'
    )
    try:
        if btn_confirmar_modal.count() > 0 and btn_confirmar_modal.first.is_visible():
            btn_confirmar_modal.first.click()
            time.sleep(2)
            logger.info("Modal confirmado.")
            return True
        else:
            logger.error("Botão Confirmar do modal não encontrado.")
            return False
    except Exception as e:
        logger.error(f"Erro ao confirmar modal: {e}")
        return False


def buscar_e_alterar(page: Page, siape: str) -> bool:
    """
    Busca o servidor pelo SIAPE e clica em Alterar.
    Retorna True se o formulário de edição carregar com sucesso.
    """
    logger.info(f"Buscando servidor SIAPE={siape}...")

    # Garante página de consulta
    if "consultar.xhtml" not in page.url:
        page.goto(CONSULTATION_URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_selector('input[name="form\\:idMskSiape"]', timeout=30000)

    campo_siape = page.locator('input[name="form\\:idMskSiape"]')
    campo_siape.clear()
    campo_siape.fill(siape)
    page.locator('role=button[name="Pesquisar"]').first.click()
    time.sleep(3)

    # Verifica se não encontrou
    alerta = page.locator("div.ui-messages-warn-summary")
    if alerta.count() > 0 and "Não foram encontrados registros" in (alerta.first.text_content() or ""):
        logger.error(f"SIAPE {siape} não encontrado no sistema.")
        return False

    # Verifica profissional inativo
    inativo = page.get_by_role("gridcell", name="Inativo", exact=True)
    if inativo.count() > 0 and inativo.first.is_visible():
        logger.error(f"Profissional SIAPE {siape} está inativo.")
        return False

    # Clicar em Alterar com múltiplos seletores
    seletores_alterar = [
        '[id="form:tabelaProfissionais:0:idAlterarCadastroProfissional"]',
        '[id$="idAlterarCadastroProfissional"]',
        'a:has(span.ico-pencil)',
    ]

    for sel in seletores_alterar:
        btn = page.locator(sel)
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            time.sleep(2)
            logger.info("Formulário de edição carregado.")
            return True

    # Fallback JS
    clicked = page.evaluate("""
        (() => {
            const links = document.querySelectorAll('a[id*="idAlterarCadastroProfissional"]');
            if (links.length > 0) { links[0].click(); return true; }
            const pencils = document.querySelectorAll('.ico-pencil');
            for (const el of pencils) {
                const anchor = el.closest('a');
                if (anchor) { anchor.click(); return true; }
            }
            return false;
        })()
    """)
    if clicked:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)
        logger.info("Formulário de edição carregado (via JS).")
        return True

    logger.error("Botão Alterar não encontrado.")
    return False


def confirmar_alteracao_final(page: Page) -> bool:
    """
    Clica no botão Confirmar principal.
    Lida com mensagem de divergência (reconfirma automaticamente).
    Retorna True se a mensagem de sucesso for detectada.
    """
    logger.info("Iniciando confirmação final...")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)

    def _clicar_confirmar():
        btn = page.locator("id=form:botaoConfirmar")
        if btn.count() > 0 and btn.is_visible():
            btn.click()
        else:
            # Fallback por role
            btn_role = page.get_by_role("button", name=" Confirmar")
            if btn_role.count() > 0 and btn_role.first.is_enabled():
                btn_role.first.click()
            else:
                page.evaluate("document.getElementById('form:botaoConfirmar').click()")

    _clicar_confirmar()

    for tentativa in range(1, 4):
        logger.info(f"Verificando resultado (tentativa {tentativa}/3)...")
        page.wait_for_timeout(3000)

        sucesso = page.locator("#mMensagens").get_by_text("Alteração realizada(o) com")
        if sucesso.count() > 0 and sucesso.first.is_visible(timeout=3000):
            logger.info("SUCESSO: Alteração realizada com sucesso!")
            return True

        # Alternativa de mensagem de sucesso
        sucesso_alt = page.locator("text=Alteração realizada")
        if sucesso_alt.count() > 0 and sucesso_alt.first.is_visible(timeout=2000):
            logger.info("SUCESSO: Alteração realizada!")
            return True

        # Divergência: reconfirmar
        divergencia = page.locator("text=diverge dos dados")
        if divergencia.count() > 0 and divergencia.first.is_visible(timeout=2000):
            logger.warning("Aviso de divergência detectado. Reconfirmando...")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            _clicar_confirmar()
            continue

    # Final check: last divergence reconfirmation may have succeeded
    page.wait_for_timeout(3000)
    sucesso = page.locator("#mMensagens").get_by_text("Alteração realizada(o) com")
    if sucesso.count() > 0 and sucesso.first.is_visible(timeout=3000):
        logger.info("SUCESSO: Alteração realizada com sucesso!")
        return True
    sucesso_alt = page.locator("text=Alteração realizada")
    if sucesso_alt.count() > 0 and sucesso_alt.first.is_visible(timeout=2000):
        logger.info("SUCESSO: Alteração realizada!")
        return True

    logger.error("Mensagem de sucesso não detectada após confirmação.")
    return False


def executar_configuracao(page: Page, siape: str, unidade: str, codigos_sv: list[str]) -> bool:
    """
    Orquestra todas as etapas de configuração de perfil.
    Retorna True em sucesso, False em falha.
    """
    logger.info(f"Iniciando configuração: SIAPE={siape} | Unidade={unidade} | SVs={codigos_sv}")

    # Etapa 1: Busca e Alterar (com retry)
    for tentativa in range(1, MAX_RETRIES + 1):
        if buscar_e_alterar(page, siape):
            break
        if tentativa < MAX_RETRIES:
            logger.warning(f"Tentativa {tentativa}/{MAX_RETRIES} falhou. Tentando novamente...")
            page.goto(CONSULTATION_URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(2)
    else:
        logger.error("Não foi possível encontrar/alterar o servidor.")
        return False

    # Etapa 2: Tabela principal de serviços
    configurar_servicos_tabela_principal(
        page, codigos_sv,
        atrib_resp=DEFAULTS["atrib_resp"],
        trasf=DEFAULTS["trasf"]
    )

    # Etapa 3: Abrir modal de competências da unidade
    if not abrir_modal_competencias_unidade(page, unidade):
        logger.error("Não foi possível abrir o modal de competências.")
        return False

    # Etapa 4: Configurar modal de competências
    if not configurar_modal_competencias(
        page, codigos_sv,
        ativar_mi_exer=DEFAULTS["ativar_mi_exer"],
        bloquear_alteracoes=DEFAULTS["bloquear_alteracoes"]
    ):
        logger.error("Falha ao configurar modal de competências.")
        return False

    # Etapa 5: Confirmação final
    if not confirmar_alteracao_final(page):
        logger.error("Confirmação final falhou.")
        return False

    logger.info(f"CONFIGURAÇÃO COMPLETA | SIAPE={siape} | Unidade={unidade}")
    return True


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
