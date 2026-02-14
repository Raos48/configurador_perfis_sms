import sys
import os
# Mova outras importações padrão como sqlite3, threading, time, datetime, openpyxl para DEPOIS deste bloco, se estiverem aqui no topo.
# A importação do Playwright virá depois.

# --- Bloco de Configuração de Caminhos para PyInstaller ---
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    application_path_sa = os.path.dirname(sys.executable)
    bundled_browsers_path = os.path.join(sys._MEIPASS, 'ms-playwright')
    if os.path.exists(bundled_browsers_path):
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = bundled_browsers_path
        print(f"INFO (saggestao_automation): PLAYWRIGHT_BROWSERS_PATH definido para: {bundled_browsers_path}")
    else:
        print(f"CRÍTICO (saggestao_automation): Pasta de navegadores empacotada '{bundled_browsers_path}' NÃO encontrada.")
else:
    application_path_sa = os.path.dirname(os.path.abspath(__file__))
    print(f"INFO (saggestao_automation): Rodando como script. Path: {application_path_sa}")

TABLE_NAME_SAGG = "sag_gestao_registros"

import sqlite3
import threading
import time
from datetime import datetime
import openpyxl
from playwright.sync_api import sync_playwright, Page, BrowserContext, Error as PlaywrightError # Import Error
import traceback
import statistics
import re

# --- Constantes ---
AUTH_STATE_FILE = "auth_state.json" # Nome do arquivo para guardar o estado da sessão

# (+) ADICIONE ESTE TRECHO NO LUGAR:
class RecoverableException(Exception):
    """Sinaliza um erro que pode ser resolvido com uma nova tentativa (e.g., timeout de página)."""
    pass

class PermanentException(Exception):
    """Sinaliza um erro que não pode ser resolvido com uma nova tentativa (e.g., SIAPE não encontrado, dados inválidos)."""
    pass


# --- Função para Obter JSESSIONID do Servidor Local ---
def obter_jsessionid_local(log_prefix="[ObterJSESSIONID]", max_retries=3, retry_delay=2):
    """
    Obtém JSESSIONID ÚNICO do servidor de autenticação local (localhost:48000).

    IMPORTANTE: Cada chamada retorna um JSESSIONID DIFERENTE do servidor,
    garantindo sessões independentes para múltiplas instâncias.

    Args:
        log_prefix: Prefixo para mensagens de log
        max_retries: Número máximo de tentativas
        retry_delay: Delay em segundos entre tentativas

    Returns:
        str: JSESSIONID válido, ou None se falhar
    """
    import requests
    import urllib3
    import json

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    url = "http://localhost:48000"
    headers = {'Comando': 'NovaSessao', 'Sistema': 'SAGGESTAO'}

    for tentativa in range(max_retries):
        try:
            print(f"{log_prefix} Tentativa {tentativa + 1}/{max_retries}: Solicitando NOVA sessão ao servidor local...")
            response = requests.get(url, headers=headers, verify=False, timeout=60)

            if response.status_code == 200:
                data = response.json()
                jsessionid = data.get('JSESSIONID')

                if jsessionid:
                    print(f"{log_prefix} JSESSIONID único obtido com sucesso: {jsessionid[:20]}...")
                    return jsessionid
                else:
                    print(f"{log_prefix} Resposta JSON inválida: chave 'JSESSIONID' não encontrada")
            else:
                print(f"{log_prefix} Servidor retornou status {response.status_code}")

        except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as e:
            print(f"{log_prefix} Erro na tentativa {tentativa + 1}: {e}")
            if tentativa < max_retries - 1:
                time.sleep(retry_delay)

    print(f"{log_prefix} Falha após {max_retries} tentativas - fallback para login manual")
    return None


# --- Função para Login Inicial e Salvar Estado ---
def perform_initial_login_and_save_state(auth_file_path, log_prefix_main):
    """
    Abre um navegador para o usuário fazer login manualmente.
    Salva o estado da sessão (cookies, etc.) se o login for bem-sucedido.
    """
    print(f"\n{log_prefix_main} --- ETAPA DE LOGIN INICIAL E SALVAMENTO DE SESSÃO ---")
    print(f"{log_prefix_main} Por favor, realize o login na janela do navegador que será aberta.")
    print(f"{log_prefix_main} A sessão será salva em '{os.path.basename(auth_file_path)}' para uso pelas demais instâncias.")

    playwright_instance = None
    browser = None
    context = None
    page = None
    login_detected_successfully = False

    try:
        playwright_instance = sync_playwright().start()
        browser = playwright_instance.chromium.launch(headless=False)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.set_default_timeout(60000) # Timeout para ações na página

        page.goto("http://psagapr01/saggestaoagu/pages/cadastro/profissional/consultar.xhtml", timeout=120000)  # 2 minutos de timeout
        page.set_viewport_size({"width": 1024, "height": 768})

        elemento_pos_login_selector = 'input[name="form\\:idMskSiape"]'
        # Timeout para o usuário realizar o login manualmente (e.g., 5 minutos)
        tempo_max_login_manual_segundos = 300 

        print(f"{log_prefix_main} Aguardando login manual ser detectado... (Timeout: {tempo_max_login_manual_segundos}s)")
        
        start_time_wait = time.time()
        while time.time() - start_time_wait < tempo_max_login_manual_segundos:
            if page.is_closed():
                print(f"{log_prefix_main} Janela de login foi fechada pelo usuário.")
                break
            try:
                # Verifica se o elemento que aparece após o login está visível
                page.wait_for_selector(elemento_pos_login_selector, state="visible", timeout=2000) # Tenta a cada 2s
                print(f"{log_prefix_main} Login detectado com sucesso!")
                login_detected_successfully = True
                break
            except PlaywrightError as e: # Especificamente Playwright TimeoutError
                if "timeout" not in str(e).lower(): # Se for outro erro do Playwright
                    print(f"{log_prefix_main} Erro do Playwright ao aguardar login: {e}")
                    raise # Propaga outros erros do Playwright
                # Se for timeout, continua no loop
            except Exception as e_general:
                print(f"{log_prefix_main} Erro geral ao aguardar detecção de login: {e_general}")
                raise # Propaga erros inesperados

            time.sleep(1) # Pausa entre verificações

        if login_detected_successfully:
            # Tenta remover o arquivo de estado antigo, se existir, para evitar problemas.
            if os.path.exists(auth_file_path):
                try:
                    os.remove(auth_file_path)
                except Exception as e_rem:
                    print(f"{log_prefix_main} AVISO: Não foi possível remover o arquivo de estado antigo '{auth_file_path}': {e_rem}")
            
            context.storage_state(path=auth_file_path)
            print(f"{log_prefix_main} Estado da sessão de login salvo com sucesso em: {auth_file_path}")
        elif not page.is_closed():
            print(f"{log_prefix_main} Login não detectado dentro do tempo limite de {tempo_max_login_manual_segundos} segundos.")
        
    except Exception as e:
        print(f"{log_prefix_main} ERRO CRÍTICO durante o processo de login inicial: {e}")
        traceback.print_exc()
        login_detected_successfully = False # Garante que retorne false em caso de erro
    finally:
        if page and not page.is_closed():
            try: page.close() 
            except Exception: pass
        if context:
            try: context.close()
            except Exception: pass
        if browser:
            try: browser.close()
            except Exception: pass
        if playwright_instance:
            try: playwright_instance.stop()
            except Exception: pass
        print(f"{log_prefix_main} --- FIM DA ETAPA DE LOGIN INICIAL ---")
    return login_detected_successfully


# --- Conversão Excel para SQLite (OTIMIZADA para arquivos grandes) ---
def excel_to_sqlite_saggestao(excel_path, db_path, table_name=TABLE_NAME_SAGG, log_prefix="[ExcelToDB]"):
    """
    Converte Excel para SQLite com otimizações para arquivos grandes (20k+ linhas).
    Usa processamento em lote e logs detalhados de progresso.
    """
    inicio_conversao = datetime.now()
    print(f"\n{log_prefix} ========== INÍCIO DA CONVERSÃO EXCEL PARA SQLITE ==========")
    print(f"{log_prefix} Arquivo Excel: {os.path.basename(excel_path)}")
    print(f"{log_prefix} Banco de Dados: {os.path.basename(db_path)}")
    print(f"{log_prefix} Hora de início: {inicio_conversao.strftime('%H:%M:%S')}")

    # Validação do arquivo Excel
    if not os.path.exists(excel_path):
        print(f"{log_prefix} ERRO CRÍTICO: Arquivo Excel '{excel_path}' não encontrado.")
        return False

    tamanho_arquivo_mb = os.path.getsize(excel_path) / (1024 * 1024)
    print(f"{log_prefix} Tamanho do arquivo: {tamanho_arquivo_mb:.2f} MB")

    # Criação do diretório do BD se necessário
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir)
            print(f"{log_prefix} INFO: Diretório '{db_dir}' criado para o banco de dados.")
        except Exception as e_dir:
            print(f"{log_prefix} ERRO CRÍTICO: Não foi possível criar o diretório '{db_dir}': {e_dir}")
            traceback.print_exc()
            return False

    # Conexão com banco de dados com timeout maior
    print(f"{log_prefix} Conectando ao banco de dados...")
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()

        # Otimizações para inserção em lote
        cursor.execute("PRAGMA synchronous = OFF")
        cursor.execute("PRAGMA journal_mode = MEMORY")
        cursor.execute("PRAGMA cache_size = 10000")
        print(f"{log_prefix} PRAGMAs de otimização aplicados ao SQLite.")
    except Exception as e_conn:
        print(f"{log_prefix} ERRO ao conectar ao banco: {e_conn}")
        traceback.print_exc()
        return False

    # Criação da tabela
    print(f"{log_prefix} Criando/verificando tabela '{table_name}'...")
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT, siape TEXT, Unidade TEXT, AtribResp TEXT, Trasf TEXT,
        AtivarMiExer TEXT, BloquerAlteracoes TEXT, ResetarTodosSv TEXT,
        AreaMeio TEXT, GrupoMeio TEXT, CodigoSv TEXT, Status TEXT
    );"""
    try:
        cursor.execute(create_table_sql)
        conn.commit()
    except Exception as e_table:
        print(f"{log_prefix} ERRO ao criar tabela: {e_table}")
        traceback.print_exc()
        conn.close()
        return False

    # Verifica se já tem dados
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    registros_existentes = cursor.fetchone()[0]
    if registros_existentes > 0:
        print(f"{log_prefix} INFO: Tabela '{table_name}' já possui {registros_existentes} registros.")
        print(f"{log_prefix} Conversão do Excel pulada (tabela não vazia).")
        conn.close()
        return True

    # Abertura do arquivo Excel
    print(f"\n{log_prefix} Abrindo arquivo Excel (isso pode levar alguns minutos para arquivos grandes)...")
    try:
        tempo_inicio_load = time.time()
        workbook = openpyxl.load_workbook(excel_path, data_only=True, read_only=True)
        sheet = workbook.active
        tempo_load = time.time() - tempo_inicio_load
        print(f"{log_prefix} ✓ Excel carregado com sucesso em {tempo_load:.2f} segundos.")
    except Exception as e:
        print(f"{log_prefix} ERRO CRÍTICO ao abrir Excel '{os.path.basename(excel_path)}':")
        print(f"{log_prefix}   Tipo de erro: {type(e).__name__}")
        print(f"{log_prefix}   Mensagem: {e}")
        traceback.print_exc()
        conn.close()
        return False

    # Leitura e validação do cabeçalho
    print(f"{log_prefix} Lendo cabeçalho do Excel...")
    try:
        header_excel_raw = [cell.value for cell in sheet[1]]
        header_excel = [str(h).strip() if h is not None else "" for h in header_excel_raw]
        print(f"{log_prefix} Total de colunas no Excel: {len(header_excel)}")
    except Exception as e_header:
        print(f"{log_prefix} ERRO ao ler cabeçalho: {e_header}")
        traceback.print_exc()
        conn.close()
        return False

    # Mapeamento de colunas
    expected_excel_headers_map = {
        "siape": ["Matricula"], "Unidade": ["Código da Unidade"],
        "AtribResp": ["Atribuição de Resposável?"], "Trasf": ["Transferência?"],
        "AtivarMiExer": ["Ativar no Micro-Exercício?"],
        "BloquerAlteracoes": ["Bloquear Alterações para Unidades Inferiores?"],
        "ResetarTodosSv": ["Resetar Todas Competências"], "AreaMeio": ["Àrea Meio?"],
        "GrupoMeio": ["Se Àrea Meio Informar o Grupo"],
    }

    print(f"{log_prefix} Mapeando colunas...")
    col_map_indices = {}
    for internal_name, excel_variants in expected_excel_headers_map.items():
        found = False
        for variant in excel_variants:
            try:
                col_map_indices[internal_name] = header_excel.index(variant)
                print(f"{log_prefix}   ✓ '{internal_name}' → coluna {col_map_indices[internal_name]} ('{variant}')")
                found = True
                break
            except ValueError:
                continue
        if not found:
            print(f"{log_prefix}   ✗ AVISO: '{internal_name}' NÃO encontrado (esperava: {excel_variants})")
            col_map_indices[internal_name] = -1

    # Validação de coluna essencial
    if col_map_indices.get("siape", -1) == -1:
        print(f"{log_prefix} ERRO FATAL: Coluna 'Matricula' (SIAPE) não encontrada no Excel.")
        print(f"{log_prefix} Colunas disponíveis: {header_excel[:10]}...")
        conn.close()
        return False

    # Detectar coluna de início dos códigos SV
    start_sv_col_index_excel = -1
    try:
        if "Status do Processamento" in header_excel:
            start_sv_col_index_excel = header_excel.index("Status do Processamento") + 1
            print(f"{log_prefix}   ✓ Códigos SV começam após 'Status do Processamento' (coluna {start_sv_col_index_excel})")
        else:
            for idx, h_item in enumerate(header_excel):
                if h_item and h_item.lower().startswith("cod"):
                    start_sv_col_index_excel = idx
                    print(f"{log_prefix}   ✓ Códigos SV começam na coluna {start_sv_col_index_excel} ('{h_item}')")
                    break
    except ValueError:
        print(f"{log_prefix}   ✗ AVISO: Não foi possível determinar coluna de início dos códigos SV")

    # Processamento das linhas com LOTE e progresso detalhado
    print(f"\n{log_prefix} Iniciando processamento de linhas...")
    print(f"{log_prefix} (Logs de progresso a cada 500 linhas)")

    rows_added = 0
    rows_skipped = 0
    rows_error = 0
    batch_data = []
    BATCH_SIZE = 500  # Insere 500 linhas por vez

    ultima_linha_processada = 0
    tempo_inicio_processamento = time.time()

    try:
        for row_num, row_cells_tuple in enumerate(sheet.iter_rows(min_row=2), start=2):
            try:
                ultima_linha_processada = row_num

                # Log de progresso a cada 500 linhas
                if row_num % 500 == 0:
                    tempo_decorrido = time.time() - tempo_inicio_processamento
                    linhas_por_segundo = (row_num - 1) / tempo_decorrido if tempo_decorrido > 0 else 0
                    print(f"{log_prefix} Linha {row_num}: {rows_added} adicionadas, {rows_skipped} puladas, {rows_error} erros ({linhas_por_segundo:.1f} linhas/seg)")

                row_values_excel = [str(cell.value).strip() if cell.value is not None else None for cell in row_cells_tuple]

                def get_value_by_internal_name(internal_col_name):
                    idx = col_map_indices.get(internal_col_name, -1)
                    return row_values_excel[idx] if idx != -1 and idx < len(row_values_excel) else None

                siape = get_value_by_internal_name("siape")

                # Pula linhas vazias
                if not siape:
                    if rows_added > 0 and any(val for val in row_values_excel if val is not None and val.strip() != ""):
                        print(f"\n{log_prefix} INFO: Fim dos dados detectado na linha {row_num} (SIAPE vazio)")
                        break
                    elif not any(val for val in row_values_excel if val is not None and val.strip() != ""):
                        rows_skipped += 1
                        continue
                    else:
                        rows_skipped += 1
                        continue

                # Extrai demais colunas
                unidade = get_value_by_internal_name("Unidade")
                atrib_resp = get_value_by_internal_name("AtribResp")
                trasf = get_value_by_internal_name("Trasf")
                ativar_mi_exer = get_value_by_internal_name("AtivarMiExer")
                bloquer_alteracoes = get_value_by_internal_name("BloquerAlteracoes")
                resetar_todos_sv = get_value_by_internal_name("ResetarTodosSv")
                area_meio = get_value_by_internal_name("AreaMeio")
                grupo_meio = get_value_by_internal_name("GrupoMeio")

                # Extrai códigos SV
                codigos_sv_list = []
                if start_sv_col_index_excel != -1:
                    for k_idx in range(start_sv_col_index_excel, len(row_values_excel)):
                        val = row_values_excel[k_idx]
                        if val is None or str(val).strip() == "":
                            break
                        codigos_sv_list.append(str(val).strip())
                codigo_sv_str = ",".join(codigos_sv_list)

                # Adiciona ao lote
                data_db = (
                    siape, unidade, atrib_resp, trasf, ativar_mi_exer,
                    bloquer_alteracoes, resetar_todos_sv, area_meio, grupo_meio,
                    codigo_sv_str, None
                )
                batch_data.append(data_db)
                rows_added += 1

                # Executa inserção em lote quando atingir o tamanho do batch
                if len(batch_data) >= BATCH_SIZE:
                    cursor.executemany(f"""INSERT INTO {table_name}
                        (siape, Unidade, AtribResp, Trasf, AtivarMiExer, BloquerAlteracoes, ResetarTodosSv, AreaMeio, GrupoMeio, CodigoSv, Status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", batch_data)
                    conn.commit()
                    batch_data = []

            except Exception as e_row:
                rows_error += 1
                print(f"{log_prefix} ERRO na linha {row_num}: {type(e_row).__name__}: {e_row}")
                if rows_error <= 5:  # Mostra traceback apenas dos primeiros 5 erros
                    traceback.print_exc()
                continue

        # Insere registros restantes do último lote
        if batch_data:
            print(f"{log_prefix} Inserindo último lote de {len(batch_data)} registros...")
            cursor.executemany(f"""INSERT INTO {table_name}
                (siape, Unidade, AtribResp, Trasf, AtivarMiExer, BloquerAlteracoes, ResetarTodosSv, AreaMeio, GrupoMeio, CodigoSv, Status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", batch_data)
            conn.commit()

    except Exception as e_processamento:
        print(f"\n{log_prefix} ERRO CRÍTICO durante processamento das linhas:")
        print(f"{log_prefix}   Última linha processada: {ultima_linha_processada}")
        print(f"{log_prefix}   Tipo de erro: {type(e_processamento).__name__}")
        print(f"{log_prefix}   Mensagem: {e_processamento}")
        traceback.print_exc()
        conn.close()
        return False
    finally:
        workbook.close()

    # Restaura configurações padrão do SQLite
    cursor.execute("PRAGMA synchronous = FULL")
    cursor.execute("PRAGMA journal_mode = DELETE")
    conn.commit()
    conn.close()

    # Relatório final
    tempo_total = (datetime.now() - inicio_conversao).total_seconds()
    print(f"\n{log_prefix} ========== CONVERSÃO CONCLUÍDA ==========")
    print(f"{log_prefix} ✓ Linhas adicionadas: {rows_added}")
    print(f"{log_prefix} ⊘ Linhas puladas: {rows_skipped}")
    print(f"{log_prefix} ✗ Linhas com erro: {rows_error}")
    print(f"{log_prefix} ⏱ Tempo total: {tempo_total:.2f} segundos ({tempo_total/60:.2f} minutos)")
    if rows_added > 0:
        print(f"{log_prefix} ⚡ Velocidade média: {rows_added/tempo_total:.1f} linhas/segundo")

    # Verificação final
    conn_check = sqlite3.connect(db_path)
    cursor_check = conn_check.cursor()
    cursor_check.execute(f"SELECT COUNT(*) FROM {table_name}")
    final_count = cursor_check.fetchone()[0]
    conn_check.close()

    print(f"{log_prefix} 📊 Total de registros no banco: {final_count}")

    if final_count == 0 and rows_added == 0:
        print(f"{log_prefix} ERRO FINAL: Nenhum registro foi inserido no banco de dados.")
        return False

    print(f"{log_prefix} ========================================\n")
    return True

# --- Funções de Gerenciamento de Progresso (sem alterações) ---
def manager_inicializar_contagem(db_path, table_name, start_id, log_prefix="[Manager]"):
    conn = sqlite3.connect(db_path, timeout=10)
    cursor = conn.cursor()
    total_registros = 0
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE (Status IS NULL OR Status = '' OR Status LIKE 'REINÍCIO%' OR Status LIKE 'ERRO%' OR Status LIKE 'Falha%') AND id >= ?", (start_id,))
        total_registros = cursor.fetchone()[0]
    except sqlite3.Error as e:
        print(f"{log_prefix} Erro SQLite ao inicializar contagem de registros em '{os.path.basename(db_path)}': {e}")
    finally:
        conn.close()
    if total_registros == 0:
        print(f"{log_prefix} INFO: Nenhum registro para processar no BD '{os.path.basename(db_path)}' a partir do ID {start_id} com status pendente.")
    return total_registros

def manager_calcular_tempo_estimado(tempos_item, processados_count, total_registros_escopo):
    if not tempos_item or processados_count == 0:
        return "Calculando..."
    tempo_medio_por_item = statistics.mean(tempos_item)
    registros_realmente_restantes = total_registros_escopo - processados_count
    if registros_realmente_restantes <= 0:
        return "Concluindo..."
    tempo_total_estimado_restante_seg = tempo_medio_por_item * registros_realmente_restantes
    horas = int(tempo_total_estimado_restante_seg // 3600)
    minutos = int((tempo_total_estimado_restante_seg % 3600) // 60)
    segundos = int(tempo_total_estimado_restante_seg % 60)
    if horas > 0:
        return f"Estimado: {horas}h {minutos}min"
    elif minutos > 0:
        return f"Estimado: {minutos}min {segundos}s"
    else:
        return f"Estimado: {segundos}s"

def manager_get_status_str(log_prefix, processados_count, total_registros_escopo, tempos_item, tempo_inicio_total_geral):
    progresso_percent = 0.0
    if total_registros_escopo > 0:
        progresso_percent = (processados_count / total_registros_escopo * 100)
    elif processados_count == total_registros_escopo and total_registros_escopo == 0:
        progresso_percent = 100.0
    decorrido_total_str = "N/A"
    if tempo_inicio_total_geral:
        decorrido_s = (datetime.now() - tempo_inicio_total_geral).total_seconds()
        h = int(decorrido_s // 3600)
        m = int((decorrido_s % 3600)//60)
        s = int(decorrido_s % 60)
        if h > 0: decorrido_total_str = f"{h}h{m}m{s}s"
        elif m > 0: decorrido_total_str = f"{m}m{s}s"
        else: decorrido_total_str = f"{s}s"
    tempo_estimado_str = manager_calcular_tempo_estimado(tempos_item, processados_count, total_registros_escopo)
    restantes_count = max(0, total_registros_escopo - processados_count)
    return (f"{log_prefix} {progresso_percent:.1f}% ({processados_count}/{total_registros_escopo}) "
            f"| Restantes: {restantes_count} | Decorrido: {decorrido_total_str} | {tempo_estimado_str}")

# --- Funções Auxiliares Playwright (sem alterações nos seletores internos por enquanto) ---
# ... (retry_find_element, click_checkbox_robust, etc. ... permanecem iguais)
def retry_find_element(page: Page, playwright_locator_string: str, max_attempts=20):
    for attempt in range(max_attempts):
        try:
            element_locator = page.locator(playwright_locator_string)
            if element_locator.count() > 0:
                return element_locator.first 
        except Exception as e:
            if attempt == max_attempts -1 :
                print(f"DEBUG: retry_find_element Tentativa {attempt + 1} falhou para seletor '{playwright_locator_string}': {e}")
        if attempt == max_attempts - 1:
            raise Exception(f"Elemento '{playwright_locator_string}' não encontrado após {max_attempts} tentativas.")
        time.sleep(1) 
    return None

def click_checkbox_robust(page: Page, checkbox_id_raw: str, condition_to_set: bool, max_attempts=3, log_prefix="[Checkbox]"):
    playwright_selector = f'[id="{checkbox_id_raw}"]'
    for attempt in range(max_attempts):
        try:
            checkbox_element = retry_find_element(page, playwright_selector, max_attempts=1) 
            if checkbox_element: 
                is_checked = checkbox_element.is_checked()
                if is_checked != condition_to_set:
                    checkbox_element.click()
                    page.wait_for_timeout(500) 
                    if checkbox_element.is_checked() == condition_to_set:
                        return True
                    else:
                        print(f"{log_prefix} AVISO: Checkbox '{checkbox_id_raw}' (seletor '{playwright_selector}') clicado, mas estado não mudou como esperado (tentativa {attempt + 1}). Estado atual: {checkbox_element.is_checked()}, Esperado: {condition_to_set}")
                else: 
                    return True 
            else:
                print(f"{log_prefix} AVISO: Checkbox com ID '{checkbox_id_raw}' (seletor '{playwright_selector}') não encontrado na tentativa {attempt + 1} de click_checkbox_robust.")
        except Exception as e:
            print(f"{log_prefix} Erro ao manusear o checkbox '{checkbox_id_raw}' (seletor '{playwright_selector}'). Tentativa {attempt + 1}. Erro: {e}")
        if attempt < max_attempts - 1:
            time.sleep(1)
        else:
            print(f"{log_prefix} FALHA após {max_attempts} tentativas no checkbox '{checkbox_id_raw}'.")
            return False 
    return False 

def print_values_procedural(db_id, siape, unidade, bloquer_alteracoes, resetar_todos_sv, area_meio, grupo_meio, codigo_sv_list, log_prefix=""):
    print(f"{log_prefix} " + "="*70)
    print(f"{log_prefix} ID BD: {db_id} | Matrícula (SIAPE): {siape} | Unidade: {unidade}")
    print(f"{log_prefix} Área Meio: {area_meio} | Grupo Meio (se Área Meio): {grupo_meio if area_meio == 'Sim' else 'N/A'}")
    print(f"{log_prefix} Bloquear Alterações p/ Unidades Inferiores: {bloquer_alteracoes}")
    print(f"{log_prefix} Resetar Todas Competências: {resetar_todos_sv}")
    print(f"{log_prefix} Códigos SV a serem configurados: {codigo_sv_list if codigo_sv_list else 'Nenhum'}")
    print(f"{log_prefix} Configurando...")

def get_total_pages_robust(page: Page, log_prefix="[Paginator]"):
    try:
        tabela_unidades_selector = "#form\\:tabelaUnidades"
        if page.locator(tabela_unidades_selector).count() > 0:
            paginator_selector = f"{tabela_unidades_selector}_paginator_bottom .ui-paginator-current"
            paginator_element = page.locator(paginator_selector)
            if paginator_element.count() > 0:
                paginator_text = paginator_element.text_content()
                if paginator_text and " de " in paginator_text:
                    match = re.search(r"(\d+)\s+de\s+(\d+)", paginator_text, re.IGNORECASE)
                    if match:
                        total_pages = int(match.group(2))
                        print(f"{log_prefix} Total de páginas da tabelaUnidades: {total_pages} (texto: '{paginator_text.strip()}')")
                        return total_pages
        tabela_container = page.locator("#form\\:pnlTabelaUnidades")
        if tabela_container.count() > 0:
            paginators_in_container = tabela_container.locator(".ui-paginator-current")
            for i in range(paginators_in_container.count()):
                paginator_element = paginators_in_container.nth(i)
                paginator_text = paginator_element.text_content()
                if paginator_text and " de " in paginator_text:
                    match = re.search(r"(\d+)\s+de\s+(\d+)", paginator_text, re.IGNORECASE)
                    if match:
                        total_pages = int(match.group(2))
                        print(f"{log_prefix} Total de páginas da tabelaUnidades (container): {total_pages} (texto: '{paginator_text.strip()}')")
                        return total_pages
        all_paginators = page.locator(".ui-paginator-current")
        for i in range(all_paginators.count()):
            paginator_element = all_paginators.nth(i)
            parent_table = paginator_element.locator("xpath=ancestor::*[contains(@id, 'tabelaServico')]")
            if parent_table.count() == 0: 
                paginator_text = paginator_element.text_content()
                if paginator_text and " de " in paginator_text:
                    match = re.search(r"(\d+)\s+de\s+(\d+)", paginator_text, re.IGNORECASE)
                    if match:
                        total_pages = int(match.group(2))
                        print(f"{log_prefix} Total de páginas (excluindo tabelaServico): {total_pages} (texto: '{paginator_text.strip()}')")
                        return total_pages
        print(f"{log_prefix} AVISO: Paginador da tabelaUnidades não encontrado, assumindo página única.")
        return 1
    except Exception as e:
        print(f"{log_prefix} ERRO ao obter total de páginas da tabelaUnidades: {e}")
        traceback.print_exc()
        return 1

def read_all_units_robust(page: Page, log_prefix="[ReadUnits]"):
    unidades = []
    try:
        # Tenta configurar a exibição para 30 itens por página para otimizar a leitura
        select_paginator_locator = page.locator("[id=\"form\\:tabelaUnidades\\:j_id7\"]")
        if select_paginator_locator.count() > 0 and select_paginator_locator.is_visible():
            select_paginator_locator.select_option("30")
            print(f"{log_prefix} Itens por página configurado para 30.")
            page.wait_for_timeout(2000) # Espera a recarga da tabela
        else:
            print(f"{log_prefix} Seletor de itens por página não visível ou não encontrado. Prosseguindo com o padrão.")
    except Exception as e:
        print(f"{log_prefix} Não possui paginação de itens por página ou erro ao configurar - prosseguindo... Erro: {e}")

    total_pages = get_total_pages_robust(page, log_prefix)
    print(f"{log_prefix} Lendo unidades de {total_pages} página(s)...")

    for page_num in range(1, total_pages + 1):
        print(f"{log_prefix} Lendo página {page_num}/{total_pages}...")
        rows_locator = page.locator("#form\\:tabelaUnidades_data tr")
        
        # Espera para garantir que as linhas estejam carregadas
        try:
            rows_locator.first.wait_for(state="visible", timeout=5000)
        except PlaywrightError:
            print(f"{log_prefix} AVISO: Nenhuma linha visível na tabela de unidades na página {page_num}.")
            break

        row_count_on_page = rows_locator.count()
        print(f"{log_prefix} Encontradas {row_count_on_page} linhas na página {page_num}.")

        for i in range(row_count_on_page):
            row = rows_locator.nth(i)
            try:
                unit_cell_locator = row.locator("td:nth-child(2)")
                if unit_cell_locator.count() > 0:
                    nome_unidade_completo = unit_cell_locator.first.text_content(timeout=2000)
                    if nome_unidade_completo and '-' in nome_unidade_completo:
                        parte_codigo = nome_unidade_completo.split('-')[0].strip()
                        codigo = parte_codigo.replace("Nome", "").strip()
                        if codigo and codigo not in unidades:
                            unidades.append(codigo)
            except Exception as e_row_read:
                print(f"{log_prefix} ERRO ao ler unidade da linha {i+1}, página {page_num}: {e_row_read}")
                continue

        # Navega para a próxima página, se não for a última
        if page_num < total_pages:
            try:
                paginator_div_selector_unidades = "[id=\"form\\:tabelaUnidades_paginator_bottom\"]"
                paginator_div_loc_unidades = page.locator(paginator_div_selector_unidades)
                next_button_locator = paginator_div_loc_unidades.locator("a.ui-paginator-next:not(.ui-state-disabled)")
                
                if next_button_locator.count() > 0:
                    print(f"{log_prefix} Clicando em 'Next Page' para ir para a página {page_num + 1}...")
                    next_button_locator.first.scroll_into_view_if_needed()
                    next_button_locator.first.click()
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2000) # Espera extra para renderização do AJAX
                else:
                    print(f"{log_prefix} Botão 'Next Page' não encontrado ou desabilitado. Interrompendo paginação.")
                    break
            except Exception as e:
                print(f"{log_prefix} Erro ao navegar para página {page_num + 1}: {str(e)}")
                break

    # --- MELHORIA ADICIONADA AQUI ---
    # Após ler todas as páginas, retorna para a primeira página para manter um estado consistente.
    try:
        print(f"{log_prefix} Leitura concluída. Retornando para a primeira página da tabela...")
        paginator_div_selector_unidades = "[id=\"form\\:tabelaUnidades_paginator_bottom\"]"
        first_page_button_locator = page.locator(f"{paginator_div_selector_unidades} a.ui-paginator-first:not(.ui-state-disabled)")
        if first_page_button_locator.count() > 0:
            first_page_button_locator.first.click()
            page.wait_for_timeout(2000) # Espera para a tabela recarregar
            print(f"{log_prefix} Tabela retornou à página 1.")
    except Exception as e_return:
        print(f"{log_prefix} AVISO: Não foi possível retornar à primeira página automaticamente. Erro: {e_return}")

    print(f"{log_prefix} Total de {len(unidades)} unidades únicas lidas.")
    return unidades

# ==============================================================================
# FUNÇÃO DE BUSCA E PROCESSAMENTO DA UNIDADE (VERSÃO MAIS ROBUSTA)
# ==============================================================================
def find_and_process_unit_robust(page: Page, unidade: str, log_prefix="[FindUnit]"):
    paginator_selector = "[id=\"form\\:tabelaUnidades_paginator_bottom\"]"

    # --- Etapa 1: Garantir que a busca comece na Página 1 (Lógica mantida) ---
    try:
        print(f"{log_prefix} Garantindo que a busca pela unidade '{unidade}' inicie na página 1...")
        first_page_button_locator = page.locator(f"{paginator_selector} a.ui-paginator-first:not(.ui-state-disabled)")
        if first_page_button_locator.count() > 0 and first_page_button_locator.is_visible():
            first_page_button_locator.first.click()
            print(f"{log_prefix} Tabela de unidades resetada para a página 1.")
            # Aumenta a espera para garantir que o AJAX conclua a atualização da tabela
            page.wait_for_timeout(3000) 
        else:
            print(f"{log_prefix} Tabela já está na página 1 ou não há paginação.")
    except Exception as e_first:
        print(f"{log_prefix} AVISO: Não foi possível clicar em 'Primeira Página'. A busca continuará da página atual. Erro: {e_first}")

    # --- Etapa 2: Loop de busca com paginação ---
    page_num = 1
    while True: 
        print(f"{log_prefix} Procurando unidade '{unidade}' na página {page_num}...")
        
        # MUDANÇA 1: ESPERA INTELIGENTE
        # Antes de iterar, espera explicitamente que a primeira linha da tabela esteja visível.
        # Isso garante que os dados da página atual foram carregados.
        try:
            page.locator("#form\\:tabelaUnidades_data tr").first.wait_for(state="visible", timeout=10000)
        except PlaywrightError:
            print(f"{log_prefix} ERRO: Nenhuma linha de dados encontrada na tabela na página {page_num}.")
            return False 

        table_rows_locator = page.locator("#form\\:tabelaUnidades_data tr")
        row_count = table_rows_locator.count()

        # Procura a unidade na página atual
        for i in range(row_count):
            row_locator = table_rows_locator.nth(i)
            print(f"{log_prefix} [DEBUG] >>> Analisando linha {i+1}/{row_count}...") # DEPURAÇÃO: Início da análise da linha

            try:
                codigo_celula_locator = row_locator.locator("td:nth-child(2)")
                if codigo_celula_locator.count() > 0:
                    codigo_celula_text = codigo_celula_locator.first.text_content(timeout=2000)
                    if codigo_celula_text:
                        # DEPURAÇÃO: Mostra o texto exato lido da célula antes de qualquer processamento
                        print(f"{log_prefix} [DEBUG] Texto bruto da célula: '{codigo_celula_text.strip()}'")
                        
                        # =============================================================
                        # CORREÇÃO APLICADA AQUI: Regex simplificada para extrair o número
                        # =============================================================
                        match = re.search(r'(\d+)', codigo_celula_text)
                        
                        if match:
                            codigo_extraido = match.group(1)
                            print(f"{log_prefix} [DEBUG] Código extraído via Regex: '{codigo_extraido}'")
                            print(f"{log_prefix} [DEBUG] Comparando: Código da linha ('{codigo_extraido}') == Unidade procurada ('{unidade}')")

                            if codigo_extraido == unidade:
                                print(f"{log_prefix} SUCESSO: Unidade {unidade} encontrada na linha {i+1}, página {page_num}.")
                                print(f"{log_prefix} [DEBUG] Tentando marcar o checkbox 'GET'...") 
                                checkbox_locator = row_locator.locator('[id$="selecionarDeselecionarGet"]')
                                if checkbox_locator.count() > 0 and checkbox_locator.is_visible():
                                    checkbox_locator.check()
                                    print(f"{log_prefix} Checkbox 'GET' da linha {i+1} selecionado.")
                                else:
                                    print(f"{log_prefix} ALERTA: Checkbox 'GET' da linha {i+1} não foi encontrado ou não está visível.")
                                
                                # =================================================================
                                # MUDANÇA 1: SELETOR DO BOTÃO MAIS ROBUSTO
                                # Procura pelo 'aria-label' OU pela classe CSS 'ico-pencil'.
                                # O método .or_() combina os seletores. Se um funcionar, ele o usa.
                                # =================================================================
                                edit_button_locator = row_locator.get_by_label("Competências do profissional por unidade").or_(row_locator.locator("a.ico-pencil"))
                                
                                # =================================================================
                                # MUDANÇA 2: LÓGICA DE RETENTATIVA (REDUNDÂNCIA)
                                # Tenta encontrar e clicar no botão por até 3 vezes antes de falhar.
                                # =================================================================
                                button_clicked_successfully = False
                                max_attempts = 3
                                for attempt in range(1, max_attempts + 1):
                                    print(f"{log_prefix} [DEBUG] Tentativa {attempt}/{max_attempts} para clicar no botão de edição...")
                                    
                                    # Verifica se o botão existe e está visível
                                    if edit_button_locator.count() > 0 and edit_button_locator.first.is_visible():
                                        try:
                                            edit_button_locator.first.click()
                                            print(f"{log_prefix} Botão de edição (lápis) clicado com sucesso.")
                                            button_clicked_successfully = True
                                            break # Se clicou com sucesso, sai do loop de tentativas
                                        except Exception as e_click:
                                            print(f"{log_prefix} [DEBUG] Erro ao tentar clicar no botão na tentativa {attempt}: {e_click}")
                                    
                                    # Se não clicou, espera 1 segundo antes da próxima tentativa
                                    if attempt < max_attempts:
                                        print(f"{log_prefix} [DEBUG] Botão não encontrado ou não clicável. Aguardando 1s...")
                                        page.wait_for_timeout(1000)

                                # Após o loop, verifica se o botão foi clicado
                                if button_clicked_successfully:
                                    page.wait_for_timeout(1000) # Espera extra para o modal começar a abrir
                                    return True # Encontrou e processou, retorna sucesso
                                else:
                                    print(f"{log_prefix} ERRO: Unidade {unidade} encontrada, mas o botão de edição não foi localizado ou clicado na linha após {max_attempts} tentativas.")
                                    return False # Falhou após todas as tentativas
                        
                        else:
                            # DEPURAÇÃO: Informa se a Regex falhou em encontrar um código
                            print(f"{log_prefix} [DEBUG] Regex não encontrou um código numérico no texto da célula.")
                    
                    
                    
                    else:
                        # DEPURAÇÃO: Informa se a célula foi encontrada mas está vazia
                        print(f"{log_prefix} [DEBUG] Célula da coluna 2 encontrada, mas sem conteúdo de texto.")
            except Exception as e_row:
                print(f"{log_prefix} ERRO GRAVE ao processar linha {i+1} da tabela: {e_row}")
                continue # Pula para a próxima linha em caso de erro inesperado



        
        # Se não encontrou na página atual, tenta ir para a próxima
        try:
            next_button_locator = page.locator(f"{paginator_selector} a.ui-paginator-next:not(.ui-state-disabled)")
            if next_button_locator.count() > 0:
                print(f"{log_prefix} Unidade não encontrada na página {page_num}. Tentando próxima página...")
                next_button_locator.first.click()
                # Aumenta a espera após clicar para a próxima página
                page.wait_for_timeout(3000) 
                page_num += 1
            else:
                print(f"{log_prefix} FIM DA BUSCA: Unidade '{unidade}' não encontrada em nenhuma página.")
                return False
        except Exception as e_nav:
            print(f"{log_prefix} ERRO ao tentar navegar para a próxima página: {e_nav}")
            return False

def verificar_e_bloquear_alteracoes_robust(page: Page, bloquear_alteracoes: str, log_prefix="[BlockChanges]"):
    base_locator = page.locator("[id=\"cmpModalCompetenciaServicoLocal\\:formPesquisaCompetencias\\:bloquearAlteracaoExercicio\"]")
    try:
        checkbox_nao_bloqueado = base_locator.get_by_text("Não")
        checkbox_bloqueado = base_locator.get_by_text("Sim")
        if checkbox_nao_bloqueado.count() == 0 or checkbox_bloqueado.count() == 0:
            print(f"{log_prefix} ERRO: Checkboxes de bloqueio não encontrados.")
            return
        radio_sim = page.locator("input[id*='bloquearAlteracaoExercicio:1']")
        esta_bloqueado = False
        if radio_sim.count() > 0:
            esta_bloqueado = radio_sim.is_checked()
        print(f"{log_prefix} Estado atual de bloqueio: {'Bloqueado' if esta_bloqueado else 'Não bloqueado'}")
        if bloquear_alteracoes == "Sim" and not esta_bloqueado:
            checkbox_bloqueado.click()
            print(f"{log_prefix} Alterações bloqueadas.")
        elif bloquear_alteracoes == "Não" and esta_bloqueado:
            checkbox_nao_bloqueado.click()
            print(f"{log_prefix} Alterações desbloqueadas.")
        else:
            print(f"{log_prefix} Estado de bloqueio já conforme desejado.")
        time.sleep(1)
    except Exception as e:
        print(f"{log_prefix} Erro ao verificar ou alterar o bloqueio: {str(e)}")

def process_code_robust(page: Page, code: str, ativar_mi_exer: str, input_playwright_selector_modal: str, log_prefix="[ProcessCode]"):
    """
    Tenta processar um único código no modal.
    - Em caso de sucesso, simplesmente retorna.
    - Em caso de falha, lança uma exceção apropriada (PermanentException ou RecoverableException).
    """
    checkbox_id_modal_raw = "cmpModalCompetenciaServicoLocal\\:formPesquisaCompetencias\\:tabelaServicoModal\\:0\\:selecionarDeselecionarCompetencia"
    checkbox_selector_modal = f'[id="{checkbox_id_modal_raw}"]'
    msg_no_records_selector_modal = "xpath=//div[@id='cmpModalCompetenciaServicoLocal:formPesquisaCompetencias:tabelaServicoModal']//td[contains(text(),'Nenhum registro encontrado')]"

    # Etapa 1: Encontrar o campo, limpar e digitar o código.
    input_field = retry_find_element(page, input_playwright_selector_modal, max_attempts=3)
    if not input_field:
        raise RecoverableException(f"Campo de entrada do código no modal não encontrado (seletor: {input_playwright_selector_modal})")

    input_field.clear()
    input_field.type(str(code), delay=50)
    print(f"{log_prefix} Código {code} digitado no campo do modal.")
    
    # Aguarda um pouco para a interface reagir à digitação (AJAX)
    page.wait_for_timeout(2000)

    # Etapa 2: Verificar o resultado da busca no modal.
    # Tentamos encontrar o checkbox que confirma que o código foi localizado.
    checkbox = retry_find_element(page, checkbox_selector_modal, max_attempts=3)
    
    if checkbox and checkbox.is_visible():
        # SUCESSO: O código foi encontrado, agora ajustamos o checkbox.
        is_checked = checkbox.is_checked()
        condition_to_set = (ativar_mi_exer == "Sim")

        if is_checked != condition_to_set:
            checkbox.click()
            print(f"{log_prefix} Checkbox {'marcado' if condition_to_set else 'desmarcado'} para o código {code}.")
        else:
            print(f"{log_prefix} Checkbox para o código {code} já está no estado desejado.")
        
        time.sleep(1) # Pequena pausa pós-clique
        return # Sucesso, finaliza a função.

    # FALHA: Se o checkbox não apareceu, verificamos se foi por um erro conhecido.
    msg_element_loc = page.locator(msg_no_records_selector_modal)
    if msg_element_loc.count() > 0 and msg_element_loc.first.is_visible():
        # É uma falha permanente: o código não existe para este profissional.
        print(f"{log_prefix} Código {code} não encontrado no modal (mensagem 'Nenhum registro').")
        raise PermanentException(f"Código SV {code} não encontrado no modal da unidade.")

    # Se não encontrou nem o checkbox nem a mensagem, é um erro inesperado (recuperável).
    raise RecoverableException(f"Resultado inesperado no modal para o código {code}. Nem checkbox nem msg de erro encontrados.")


def wait_for_table_update_robust(page: Page, cod: str, log_prefix="[TableUpdate]", timeout=7):
    table_cell_selector_geral = f"//tbody[@id='form:tabelaServico_data']/tr/td[normalize-space(text())='{str(cod)}']"
    msg_no_records_selector_geral = "//tbody[@id='form:tabelaServico_data']/tr/td[contains(text(),'Nenhum registro encontrado')]"
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            element_locator = page.locator(table_cell_selector_geral)
            if element_locator.count() > 0 and element_locator.first.is_visible():
                print(f"{log_prefix} Tabela (geral) atualizada com o código {cod}")
                return True
        except Exception as e_find: 
            print(f"{log_prefix} DEBUG: Exceção ao buscar célula {cod}: {e_find}")
            pass
        try:
            mensagem_locator = page.locator(msg_no_records_selector_geral)
            if mensagem_locator.count() > 0 and mensagem_locator.first.is_visible():
                print(f"{log_prefix} Tabela (geral) mostra 'Nenhum registro encontrado' para código {cod}")
                return "NENHUM_REGISTRO"
        except Exception as e_msg: 
            print(f"{log_prefix} DEBUG: Exceção ao buscar msg 'nenhum registro': {e_msg}")
            pass
        time.sleep(0.5)
    print(f"{log_prefix} Timeout: A tabela (geral) não foi atualizada com o código {cod} ou mensagem 'Nenhum registro' não apareceu.")
    return False

def confirmar_e_processar_robust(page: Page, db_conn, table_name: str, registro_id_db: int, log_prefix="[Confirm]"):
    botao_confirmar_locator = page.get_by_role("button", name=" Confirmar")
    mensagem_sucesso_locator = page.locator("#mMensagens").get_by_text("Alteração realizada(o) com")
    mensagem_divergencia_locator = page.locator("#mMensagens").get_by_text("Horário diverge dos dados do")
    mensagem_feedback_selector = "div.ui-messages-info-summary, div.ui-messages-error-summary, div.ui-messages-warn-summary"
    status_final_para_db = f"ERRO: Falha desconhecida na etapa de confirmação para ID {registro_id_db}"
    sucesso_operacao_principal = False
    try:
        print(f"{log_prefix} Confirmando alterações principais para ID {registro_id_db}...")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        if botao_confirmar_locator.count() > 0 and botao_confirmar_locator.first.is_enabled():
            botao_confirmar_locator.click()
            print(f"{log_prefix} Botão Confirmar principal clicado com sucesso.")
            page.wait_for_timeout(3000) 
            try:
                mensagem_divergencia_locator.wait_for(timeout=5000) 
                if mensagem_divergencia_locator.count() > 0:
                    mensagem_divergencia_texto = mensagem_divergencia_locator.first.text_content()
                    print(f"{log_prefix} Mensagem de divergência detectada: '{mensagem_divergencia_texto}'")
                    print(f"{log_prefix} Mensagem de divergência detectada. Confirmando novamente.")
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    botao_confirmar_divergencia = page.get_by_role("button", name=" Confirmar")
                    if botao_confirmar_divergencia.count() > 0 and botao_confirmar_divergencia.first.is_enabled():
                        botao_confirmar_divergencia.click()
                        print(f"{log_prefix} Segundo clique no botão Confirmar realizado.")
                        page.wait_for_timeout(3000)
                        try:
                            mensagem_sucesso_locator.wait_for(timeout=5000)
                            if mensagem_sucesso_locator.count() > 0:
                                mensagem_sucesso_final = mensagem_sucesso_locator.first.text_content()
                                print(f"{log_prefix} Mensagem de sucesso após segunda tentativa: '{mensagem_sucesso_final}'")
                                status_final_para_db = "Alteração realizada(o) com sucesso."
                                sucesso_operacao_principal = True
                                print(f"{log_prefix} SUCESSO: Alteração realizada com sucesso!")
                            else:
                                mensagem_final_loc = page.locator(mensagem_feedback_selector)
                                if mensagem_final_loc.count() > 0:
                                    status_final_para_db = mensagem_final_loc.first.text_content()
                                else:
                                    status_final_para_db = "Sem mensagem de confirmação após segunda tentativa de clique."
                        except Exception:
                            print(f"{log_prefix} Mensagem de sucesso não apareceu após segunda tentativa.")
                            mensagem_final_loc = page.locator(mensagem_feedback_selector)
                            if mensagem_final_loc.count() > 0:
                                status_final_para_db = mensagem_final_loc.first.text_content()
                            else:
                                status_final_para_db = "Sem mensagem de confirmação após segunda tentativa de clique."
                    else:
                        status_final_para_db = "Botão de confirmar não encontrado/habilitado para segunda tentativa."
                else:
                    print(f"{log_prefix} Não há mensagem de divergência, verificando mensagem de sucesso...")
            except Exception:
                print(f"{log_prefix} Mensagem de divergência não apareceu, verificando mensagem de sucesso...")
                try:
                    mensagem_sucesso_locator.wait_for(timeout=5000)
                    if mensagem_sucesso_locator.count() > 0:
                        mensagem_sucesso_texto = mensagem_sucesso_locator.first.text_content()
                        print(f"{log_prefix} Mensagem de sucesso detectada: '{mensagem_sucesso_texto}'")
                        status_final_para_db = "Alteração realizada(o) com sucesso."
                        sucesso_operacao_principal = True
                        print(f"{log_prefix} SUCESSO: Alteração realizada com sucesso!")
                    else:
                        mensagem_element_loc = page.locator(mensagem_feedback_selector)
                        if mensagem_element_loc.count() > 0:
                            status_final_para_db = mensagem_element_loc.first.text_content()
                        else:
                            status_final_para_db = "Não foi possível encontrar mensagem de feedback após clique."
                except Exception:
                    print(f"{log_prefix} Mensagem de sucesso também não apareceu, verificando outras mensagens...")
                    mensagem_element_loc = page.locator(mensagem_feedback_selector)
                    if mensagem_element_loc.count() > 0:
                        status_final_para_db = mensagem_element_loc.first.text_content()
                    else:
                        raise RecoverableException(f"Não foi possível encontrar mensagem de feedback após clique - Será realizada nova tentativa.")
            print(f"{log_prefix} Processo concluído com mensagem: {status_final_para_db}")
        else:
            status_final_para_db = f"Botão Confirmar principal não encontrado ou desabilitado."
            print(f"{log_prefix} {status_final_para_db}")
    except Exception as e:
        status_final_para_db = f"ERRO durante confirmação: {str(e)}"
        print(f"{log_prefix} {status_final_para_db}")
        traceback.print_exc()
    finally:
        try:
            cursor_db_update = db_conn.cursor()
            status_db_cortado = (status_final_para_db[:250] + '...') if len(status_final_para_db) > 253 else status_final_para_db
            cursor_db_update.execute(f"UPDATE {table_name} SET Status = ? WHERE id = ?", (status_db_cortado, registro_id_db))
            db_conn.commit()
            print(f"{log_prefix} Status '{status_db_cortado}' salvo no BD para ID {registro_id_db}.")
        except Exception as e_db_update_status:
            print(f"{log_prefix} ERRO ao atualizar status no BD: {e_db_update_status}")
    return sucesso_operacao_principal

# --- Função Principal de Automação (Modificada) ---
# (+) SUBSTITUA SUA FUNÇÃO INTEIRA POR ESTA:

# --- Exceções Customizadas (Versão Final) ---
class RecoverableException(Exception):
    """Sinaliza um erro que pode ser resolvido com uma nova tentativa (e.g., timeout de página)."""
    pass

class PermanentException(Exception):
    """Sinaliza um erro que não pode ser resolvido com uma nova tentativa (e.g., SIAPE não encontrado, dados inválidos)."""
    pass


# --- Função Principal de Automação (Versão Final Completa) ---
def run_automation_saggestao(db_file_path, stop_event=None, start_id=1, instancia_id=1, auth_state_path=None):
    if stop_event is None: stop_event = threading.Event()
    log_prefix_instancia = f"[SAGGestao I{instancia_id} SID:{start_id}]"

    if not db_file_path or not os.path.exists(db_file_path):
        print(f"{log_prefix_instancia} ERRO CRÍTICO: Arquivo de banco de dados '{db_file_path}' não encontrado.")
        return

    total_registros_escopo_atual = manager_inicializar_contagem(db_file_path, TABLE_NAME_SAGG, start_id, log_prefix_instancia)
    if total_registros_escopo_atual == 0:
        print(f"{log_prefix_instancia} Nenhuma tarefa a ser executada.")
        return
        
    registros_processados_nesta_exec = 0
    tempos_processamento_item_lista = []
    tempo_inicio_total_geral_exec = datetime.now()

    print(f"{log_prefix_instancia} Iniciando automação. Total de registros a processar: {total_registros_escopo_atual}")

    playwright_instance = None; browser = None; context = None; page = None; db_conn_main_loop = None

    try:
        # ===== NOVA LÓGICA: OBTER JSESSIONID INDEPENDENTE =====
        print(f"{log_prefix_instancia} Obtendo sessão independente do servidor localhost...")
        jsessionid = obter_jsessionid_local(log_prefix_instancia)

        playwright_instance = sync_playwright().start()
        browser = playwright_instance.chromium.launch(headless=False)

        if jsessionid:
            # AUTO-LOGIN: Injetar cookie obtido do servidor
            print(f"{log_prefix_instancia} Criando contexto com JSESSIONID independente...")
            context = browser.new_context(ignore_https_errors=True)

            cookie_para_injetar = {
                "name": "JSESSIONID",
                "value": jsessionid,
                "url": "http://psagapr01"
            }
            context.add_cookies([cookie_para_injetar])
            print(f"{log_prefix_instancia} Cookie JSESSIONID injetado com sucesso!")
        else:
            # FALLBACK: Login manual
            print(f"{log_prefix_instancia} Servidor indisponível - FALLBACK para login manual!")
            print(f"{log_prefix_instancia} AGUARDANDO login manual do usuário (timeout: 300s)...")
            context = browser.new_context(ignore_https_errors=True)
            # Não injeta cookie - usuário fará login manual

        page = context.new_page()
        page.set_default_timeout(45000)
        db_conn_main_loop = sqlite3.connect(db_file_path, timeout=15)

        page.goto("http://psagapr01/saggestaoagu/pages/cadastro/profissional/consultar.xhtml",
                  wait_until="domcontentloaded", timeout=120000)  # 2 minutos de timeout

        # ===== SELEÇÃO DE DOMÍNIO (se necessário) =====
        try:
            print(f"{log_prefix_instancia} Verificando se é necessário selecionar domínio...")
            # Aguardar 2 segundos para a página carregar completamente
            time.sleep(2)

            # Verificar se o seletor de domínio está presente
            domain_selector = page.locator('select#domains')
            if domain_selector.count() > 0:
                print(f"{log_prefix_instancia} Página de seleção de domínio detectada!")

                # Selecionar o domínio UO:01.001.PRES
                print(f"{log_prefix_instancia} Selecionando domínio UO:01.001.PRES...")
                domain_selector.select_option("UO:01.001.PRES")
                time.sleep(1)

                # Clicar no botão Enviar
                print(f"{log_prefix_instancia} Clicando no botão 'Enviar'...")
                page.get_by_role("button", name="Enviar").click()

                # Aguardar navegação após submissão
                print(f"{log_prefix_instancia} Aguardando redirecionamento após seleção de domínio...")
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                time.sleep(2)
                print(f"{log_prefix_instancia} Domínio selecionado com sucesso!")
            else:
                print(f"{log_prefix_instancia} Página de seleção de domínio não detectada - prosseguindo...")
        except Exception as e_domain:
            print(f"{log_prefix_instancia} Aviso ao processar seleção de domínio: {e_domain}")
            print(f"{log_prefix_instancia} Continuando com o fluxo normal...")

        # Aguardar confirmação de login (manual OU automático)
        elemento_pos_login_selector = 'input[name="form\\:idMskSiape"]'
        try:
            print(f"{log_prefix_instancia} Verificando confirmação do login...")
            page.wait_for_selector(elemento_pos_login_selector, state="visible", timeout=300000)
            print(f"{log_prefix_instancia} Login confirmado com sucesso!")
        except PlaywrightError:
            print(f"{log_prefix_instancia} ERRO: Login não detectado no tempo limite. Encerrando instância.")
            return

        print(f"{log_prefix_instancia} --- INÍCIO DO PROCESSAMENTO DE DADOS ---")
        
        while not stop_event.is_set():
            registro_db_atual_processar = None
            db_id_atual = -1

            try:
                cursor_busca = db_conn_main_loop.cursor()
                query_busca = f"SELECT * FROM {TABLE_NAME_SAGG} WHERE (Status IS NULL OR Status = '' OR Status LIKE 'REINÍCIO%' OR Status LIKE 'ERRO%' OR Status LIKE 'Falha%') AND id >= ? ORDER BY id ASC LIMIT 1"
                cursor_busca.execute(query_busca, (start_id,))
                registro_db_atual_processar = cursor_busca.fetchone()
            except Exception as e_db_busca:
                print(f"{log_prefix_instancia} Erro ao buscar próximo registro no BD: {e_db_busca}")
                time.sleep(5)
                continue

            if not registro_db_atual_processar:
                print(f"\n{log_prefix_instancia} Não há mais registros pendentes para processar.")
                break

            (db_id_atual, siape_atual, unidade_cod_atual, atrib_resp_str_atual, trasf_str_atual, ativar_mi_exer_str_atual,
             bloquer_alteracoes_str_atual, resetar_todos_sv_str_atual, area_meio_str_atual, 
             grupo_meio_str_atual, codigo_sv_str_db_atual, _) = registro_db_atual_processar
            
            codigo_sv_lista_para_processar = [cod.strip() for cod in codigo_sv_str_db_atual.split(',') if cod.strip()] if codigo_sv_str_db_atual else []
            
            cursor_update = db_conn_main_loop.cursor()
            cursor_update.execute(f"UPDATE {TABLE_NAME_SAGG} SET Status = ? WHERE id = ?", (f"Em processamento (I{instancia_id})", db_id_atual))
            db_conn_main_loop.commit()

            tempo_inicio_item = datetime.now()
            print_values_procedural(db_id_atual, siape_atual, unidade_cod_atual, bloquer_alteracoes_str_atual, resetar_todos_sv_str_atual, area_meio_str_atual, grupo_meio_str_atual, codigo_sv_lista_para_processar, log_prefix_instancia)
            
            max_tentativas_por_item = 3
            
            for tentativa_atual in range(1, max_tentativas_por_item + 1):
                if stop_event.is_set(): break
                
                log_prefix_tentativa = f"{log_prefix_instancia} [ID: {db_id_atual} | Tentativa {tentativa_atual}/{max_tentativas_por_item}]"
                print(f"\n{log_prefix_tentativa} Iniciando...")

                try:
                    # ==================================================================
                    # INÍCIO DA LÓGICA DE AUTOMAÇÃO INTEGRADA
                    # ==================================================================
                    
                    page.goto("http://psagapr01/saggestaoagu/pages/cadastro/profissional/consultar.xhtml", wait_until="domcontentloaded", timeout=120000)  # 2 minutos de timeout
                    time.sleep(1)

                    # --- Etapa 1: Busca pelo SIAPE ---
                    campo_siape_selector = 'input[name="form\\:idMskSiape"]'
                    botao_pesquisar_selector = 'role=button[name="Pesquisar"]'
                    alerta_nao_encontrado_selector = 'div.ui-messages-warn-summary'
                    
                    campo_siape = retry_find_element(page, campo_siape_selector)
                    campo_siape.clear()
                    campo_siape.fill(siape_atual)
                    page.locator(botao_pesquisar_selector).first.click()
                    time.sleep(3) # Aguarda a busca
                    
                    alerta_element_loc = page.locator(alerta_nao_encontrado_selector)
                    if alerta_element_loc.count() > 0 and "Não foram encontrados registros" in alerta_element_loc.first.text_content():
                        raise PermanentException(f"SIAPE {siape_atual} não encontrado.")

                    # --- Etapa 2: Verifica Status do Profissional ---
                    status_inativo_loc = page.get_by_role("gridcell", name="Inativo", exact=True)
                    if status_inativo_loc.count() > 0 and status_inativo_loc.first.is_visible():
                        raise PermanentException("Profissional Inativo.")

                    # --- Etapa 3: Clica em Alterar ---
                    link_alterar_loc = page.locator('role=link[name=""]').or_(page.locator('[id="form:tabelaProfissionais:0:idAlterarCadastroProfissional"]'))
                    if link_alterar_loc.count() > 0:
                        link_alterar_loc.first.click()
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                        time.sleep(2)
                    else:
                        raise RecoverableException("Link 'Alterar' não encontrado. Tentando novamente.")
                    

                    # --- Etapa 4: Validações de Cadastro ---
                    if page.locator('div.ui-messages-error-summary').count() > 0:
                        raise RecoverableException(f"Erro geral do sistema detectado após clicar em alterar: {page.locator('div.ui-messages-error-summary').first.text_content()}")
                    
                    if not page.locator('[id^="form:tipoAreaTrabalho:"][checked]').count():
                        raise PermanentException("Cadastro do Servidor incompleto (nenhuma área de trabalho selecionada).")
                    
                    # --- Etapa 5: Processamento da Unidade ---
                    try:
                        select_pag_unidades_locator = page.locator("[id=\"form\\:tabelaUnidades\\:j_id7\"]")
                        if select_pag_unidades_locator.count() > 0 and select_pag_unidades_locator.is_visible():
                            select_pag_unidades_locator.select_option(value="30")
                            time.sleep(2)
                    except Exception:
                        print(f"{log_prefix_tentativa} AVISO: Paginação de unidades não encontrada ou falhou ao configurar.")
                    
                    unidades_lidas = read_all_units_robust(page, log_prefix_tentativa)
                    if str(unidade_cod_atual) not in unidades_lidas:
                        print(f"Unidade {unidade_cod_atual} não localizada realizando a inclusão...")
                        campo_busca_unid_locator = page.locator('[id="form\\:inputCodigoUnidade"]')
                        if campo_busca_unid_locator.count() > 0:
                            campo_busca_unid_locator.fill(unidade_cod_atual)
                            campo_busca_unid_locator.press("Enter")
                            time.sleep(2.5)
                            unidades_lidas_apos_filtro = read_all_units_robust(page, log_prefix_tentativa + "[Pós-Filtro]")
                            if str(unidade_cod_atual) not in unidades_lidas_apos_filtro:
                                raise RecoverableException(f"Unidade {unidade_cod_atual} não encontrada mesmo após filtro.")
                        else:
                            raise RecoverableException("Campo de filtro de unidade não encontrado.")
                    else:
                        print(f"Unidade {unidade_cod_atual} localizada!")
                    
                    # --- Etapa 6: Configuração de Área Meio ---
                    if area_meio_str_atual == "Sim":
                        print(f"{log_prefix_tentativa} Configurando Área Meio: Sim, Grupo: {grupo_meio_str_atual}")
                        page.once("dialog", lambda dialog: dialog.accept())
                        page.locator("[id=\"form\\:grupoServicoareaFim\"]").get_by_text("Não").click()
                        time.sleep(1.5)
                        
                        page.once("dialog", lambda dialog: dialog.accept())
                        dropdown_label_locator = page.locator("[id=\"form\\:selectGrupoServico_label\"]")
                        dropdown_label_locator.click()
                        time.sleep(1)
                        
                        item_grupo_locator = page.locator(f"#form\\:selectGrupoServico_items li[data-label='{grupo_meio_str_atual}']")
                        item_grupo_locator.first.click()
                        time.sleep(1.5)

                    # --- Etapa 7: Processamento de Códigos SV na Tabela Principal ---
                    for cod_sv in codigo_sv_lista_para_processar:
                        if not cod_sv: continue
                        
                        print(f"{log_prefix_tentativa} Processando código SV {cod_sv} na tabela principal...")
                        input_cod_sv_geral_selector = '[id="form\\:tabelaServico\\:codigoServico"]'
                        input_element_geral = retry_find_element(page, input_cod_sv_geral_selector, max_attempts=5)

                        
                        if not input_element_geral: continue


                        # 1. Limpeza Robusta: Simula um usuário limpando o campo manualmente.
                        try:
                            # Foca no elemento para garantir que ele receba os comandos
                            input_element_geral.focus()
                            # Clica 3 vezes para selecionar todo o conteúdo do input
                            input_element_geral.click(click_count=3) 
                            # Pressiona Backspace para apagar o conteúdo selecionado
                            input_element_geral.press('Backspace') 
                        except Exception as e:
                            print(f"{log_prefix_tentativa} Erro ao tentar limpar o campo de input para o código {cod_sv}. {e}")
                            continue

                        input_element_geral.clear()
                        input_element_geral.type(str(cod_sv), delay=100)
                        # Pausa para o filtro da tabela ser aplicado via AJAX
                        page.wait_for_timeout(2000)
                        
                        # CORREÇÃO APLICADA AQUI
                        sv_code_cell_locator = page.get_by_role("gridcell", name=str(cod_sv), exact=True).filter(visible=True)
                        empty_message_locator = page.get_by_text("Nenhum registro encontrado.")
                        
                        try:
                            combined_locator = sv_code_cell_locator.or_(empty_message_locator)
                            combined_locator.first.wait_for(state="visible", timeout=10000)
                        except Exception as e:
                            print(f"{log_prefix_tentativa} Timeout: A tabela não atualizou após o filtro para o código {cod_sv}. {e}")
                            page.screenshot(path=f"erro_timeout_filtro_{cod_sv}.png")
                            continue
                        
                        
                        # 4. Verificação do Resultado (lógica mantida, pois é robusta).
                        if sv_code_cell_locator.is_visible():
                            print(f"{log_prefix_tentativa} Código SV {cod_sv} encontrado com sucesso na tabela.")
                            try:
                                # Esperamos que essa célula ÚNICA e EXATA apareça.
                                sv_code_cell_locator.wait_for(state="visible", timeout=15000)
                                row_locator = sv_code_cell_locator.locator("xpath=ancestor::tr")
                                
                                # Busca os checkboxes dentro daquela linha específica
                                print(f"{log_prefix_tentativa} Linha para SV {cod_sv} encontrada. Configurando checkboxes...")
                                checkbox_comp_id = row_locator.locator("input[name*='selecionarDeselecionarCompetencia']").get_attribute("id")
                                click_checkbox_robust(page, checkbox_comp_id, True, log_prefix=log_prefix_tentativa)
                                
                                checkbox_atrib_id = row_locator.locator("input[name*='selecionarDeselecionarAtribuicao']").get_attribute("id")
                                click_checkbox_robust(page, checkbox_atrib_id, atrib_resp_str_atual == "Sim", log_prefix=log_prefix_tentativa)

                                checkbox_transf_id = row_locator.locator("input[name*='selecionarDeselecionarTransferencia']").get_attribute("id")
                                click_checkbox_robust(page, checkbox_transf_id, trasf_str_atual == "Sim", log_prefix=log_prefix_tentativa)

                            except Exception as e:
                                print(f"{log_prefix_tentativa} ERRO: Não foi possível localizar a linha exata para o código SV {cod_sv} após o filtro.")
                                # Lança uma exceção para que a lógica de nova tentativa da função principal possa lidar com isso.
                                raise RecoverableException(f"Não foi possível processar o código SV {cod_sv} na tabela principal.") from e

                        elif empty_message_locator.is_visible():
                            print(f"{log_prefix_tentativa} Falha: Código SV {cod_sv} não resultou em nenhum registro na tabela.")
                            continue
                            
                        else:
                            print(f"{log_prefix_tentativa} Estado inesperado da tabela para o código {cod_sv}.")
                            page.screenshot(path=f"erro_inesperado_filtro_{cod_sv}.png")
                            continue
                        
                        


                    # --- Etapa 8: Processamento no Modal de Competências da Unidade ---
                    if find_and_process_unit_robust(page, str(unidade_cod_atual), log_prefix_tentativa):
                        verificar_e_bloquear_alteracoes_robust(page, bloquer_alteracoes_str_atual, log_prefix_tentativa)
                        
                        input_cod_sv_modal_selector = '[id="cmpModalCompetenciaServicoLocal\\:formPesquisaCompetencias\\:tabelaServicoModal\\:codigoModalServico"]'
                        for codigo_sv_modal_loop in codigo_sv_lista_para_processar:
                            if not codigo_sv_modal_loop: continue
                            process_code_robust(page, codigo_sv_modal_loop, ativar_mi_exer_str_atual, input_cod_sv_modal_selector, log_prefix_tentativa)

                        botao_confirmar_modal_selector = '[id="cmpModalCompetenciaServicoLocal\\:formPesquisaCompetencias\\:botaoConfirmarModalCompetenciaServicoLocal"]'
                        page.locator(botao_confirmar_modal_selector).first.click()
                        time.sleep(2)
                    else:
                        raise RecoverableException(f"Falha ao encontrar a unidade {unidade_cod_atual} para abrir o modal de competências.")

                    # --- Etapa 9: Confirmação Final ---
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)
                    resultado_final = confirmar_e_processar_robust(page, db_conn_main_loop, TABLE_NAME_SAGG, db_id_atual, log_prefix_tentativa)

                    if resultado_final:
                        print(f"{log_prefix_tentativa} SUCESSO: Item processado e confirmado.")
                        break # Sucesso! Sai do laço de tentativas.
                    else:
                        raise RecoverableException("A etapa de confirmação final não indicou sucesso (sem mensagem de êxito).")

                # ==================================================================
                # FIM DA LÓGICA DE AUTOMAÇÃO / INÍCIO DO TRATAMENTO DE ERROS
                # ==================================================================
                except PermanentException as e_perm:
                    print(f"{log_prefix_tentativa} ERRO PERMANENTE: {e_perm}")
                    status_final = f"FALHA (Permanente): {str(e_perm)}"
                    cursor_update.execute(f"UPDATE {TABLE_NAME_SAGG} SET Status = ? WHERE id = ?", (status_final[:255], db_id_atual))
                    db_conn_main_loop.commit()
                    break 
                
                except (RecoverableException, PlaywrightError, Exception) as e_rec:
                    mensagem_erro = f"{type(e_rec).__name__}: {str(e_rec)}"
                    print(f"{log_prefix_tentativa} ERRO: {mensagem_erro}")
                    traceback.print_exc()

                    if tentativa_atual < max_tentativas_por_item:
                        status_tentativa = f"REINÍCIO ({tentativa_atual}/{max_tentativas_por_item}): {mensagem_erro[:150]}"
                        cursor_update.execute(f"UPDATE {TABLE_NAME_SAGG} SET Status = ? WHERE id = ?", (status_tentativa[:255], db_id_atual))
                        db_conn_main_loop.commit()
                        print(f"{log_prefix_tentativa} Aguardando 5s para tentar novamente...")
                        time.sleep(5)
                    else:
                        print(f"{log_prefix_tentativa} Limite de tentativas atingido. Marcando como falha persistente.")
                        status_final = f"FALHA (Persistente): {mensagem_erro[:150]}"
                        cursor_update.execute(f"UPDATE {TABLE_NAME_SAGG} SET Status = ? WHERE id = ?", (status_final[:255], db_id_atual))
                        db_conn_main_loop.commit()
            
            # --- Finaliza o processamento do item e atualiza as estatísticas ---
            tempo_fim_item = datetime.now()
            tempo_gasto_item = (tempo_fim_item - tempo_inicio_item).total_seconds()
            tempos_processamento_item_lista.append(tempo_gasto_item)
            registros_processados_nesta_exec += 1
            print(manager_get_status_str(log_prefix_instancia, registros_processados_nesta_exec, total_registros_escopo_atual, tempos_processamento_item_lista, tempo_inicio_total_geral_exec), end='\r', flush=True)

            start_id = db_id_atual + 1
            time.sleep(1)

        print(f"\n{log_prefix_instancia} --- PROCESSAMENTO CONCLUÍDO ---")

    except KeyboardInterrupt:
        print(f"\n{log_prefix_instancia} --- INTERRUPÇÃO MANUAL ---")
    except Exception as e_fatal:
        print(f"\n{log_prefix_instancia} --- ERRO CRÍTICO NA AUTOMAÇÃO: {e_fatal} ---")
        traceback.print_exc()
    finally:
        print(f"\n{log_prefix_instancia} --- FINALIZANDO SESSÃO ---")
        if stop_event: stop_event.set()
        if page and not page.is_closed():
            try: page.close()
            except Exception as e: print(f"{log_prefix_instancia} Erro ao fechar página: {e}")
        if context:
            try: context.close()
            except Exception as e: print(f"{log_prefix_instancia} Erro ao fechar contexto: {e}")
        if browser:
            try: browser.close()
            except Exception as e: print(f"{log_prefix_instancia} Erro ao fechar navegador: {e}")
        if playwright_instance:
            try: playwright_instance.stop()
            except Exception as e: print(f"{log_prefix_instancia} Erro ao parar Playwright: {e}")
        if db_conn_main_loop:
            try: db_conn_main_loop.close()
            except Exception as e: print(f"{log_prefix_instancia} Erro ao fechar conexão com BD: {e}")