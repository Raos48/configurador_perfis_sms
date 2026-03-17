"""
Serviço RPA de Bloqueio de Perfis - Loop Principal de Polling.

Este script é o ponto de entrada do serviço. Ele:
1. Conecta-se à API do Sistema SIGA via JWT
2. Busca pedidos pendentes de bloqueio e desbloqueio
3. Executa cada pedido no SAGGESTAO via browser automation
4. Confirma o resultado de volta à API
5. Aguarda e repete

Uso:
    python servico_rpa.py

Para encerrar: Ctrl+C
"""

import time
import logging
import sys
from typing import Literal

from config import (
    SIGA_API_URL,
    SIGA_EMAIL,
    SIGA_PASSWORD,
    POLLING_INTERVAL,
    POLLING_INTERVAL_IDLE,
    LOG_FILE,
    LOG_LEVEL,
    API_ENV,
)
from siga_client import SigaApiClient
from bloquear_perfis import executar_bloqueio
from session_manager import SaggestaoSessionManager
from colored_logger import setup_colored_logging, print_startup_banner, print_shutdown_banner, print_heartbeat
from metrics import MetricsCollector

# ============================================
# Configuração de Logging com Cores
# ============================================
log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
setup_colored_logging(log_level=log_level, log_file=LOG_FILE)
logger = logging.getLogger("RPA.Servico")


def processar_pendentes(
    cliente: SigaApiClient, 
    session_manager: SaggestaoSessionManager,
    tipo_acao: Literal["BLOQUEIO", "DESBLOQUEIO"],
    metrics: MetricsCollector
) -> int:
    """
    Busca e processa bloqueios ou desbloqueios pendentes.
    Unifica a lógica de processamento para ambos os tipos de ação.

    Args:
        cliente: Cliente autenticado da API SIGA.
        session_manager: Gerenciador de sessão do navegador.
        tipo_acao: "BLOQUEIO" ou "DESBLOQUEIO".
        metrics: Coletor de métricas para registro.

    Returns:
        Quantidade de itens processados.
    """
    try:
        if tipo_acao == "BLOQUEIO":
            pendentes = cliente.buscar_pendentes_bloqueio()
        else:
            pendentes = cliente.buscar_pendentes_desbloqueio()
    except Exception as e:
        logger.error(f"Erro ao buscar pendentes de {tipo_acao}: {e}")
        return 0

    if not pendentes:
        return 0

    logger.info(f"Encontrados {len(pendentes)} pedido(s) de {tipo_acao} pendente(s).")
    processados = 0

    for item in pendentes:
        start_time = time.time()
        bloqueio_id = item['id']
        siape = item['servidor']['siape']
        codigo_unidade = item['codigo_unidade']
        sucesso = False

        logger.info(f"[{tipo_acao} #{bloqueio_id}] Iniciando: SIAPE={siape}, Unidade={codigo_unidade}")

        try:
            sucesso, erro = executar_bloqueio(siape, codigo_unidade, tipo_acao, session_manager)

            # Confirmar resultado na API
            try:
                msg_erro = erro or ""
                if tipo_acao == "BLOQUEIO":
                    cliente.confirmar_bloqueio(bloqueio_id, sucesso, msg_erro)
                else:
                    cliente.confirmar_desbloqueio(bloqueio_id, sucesso, msg_erro)

                if sucesso:
                    logger.info(f"[{tipo_acao} #{bloqueio_id}] SUCESSO - Confirmado na API.")
                else:
                    logger.warning(f"[{tipo_acao} #{bloqueio_id}] FALHA - {erro} - Reportado à API.")
            
            except Exception as e:
                logger.error(f"[{tipo_acao} #{bloqueio_id}] Erro ao confirmar na API: {e}")

        except Exception as e:
            # Erro inesperado na automação - tenta reportar à API
            msg = f"Erro inesperado na automação: {str(e)}"
            logger.error(f"[{tipo_acao} #{bloqueio_id}] {msg}")
            try:
                if tipo_acao == "BLOQUEIO":
                    cliente.confirmar_bloqueio(bloqueio_id, False, msg[:500])
                else:
                    cliente.confirmar_desbloqueio(bloqueio_id, False, msg[:500])
            except Exception:
                logger.error(f"[{tipo_acao} #{bloqueio_id}] Falha ao reportar erro à API.")
        
        # Registrar métrica
        duration = time.time() - start_time
        metrics.record_operation(tipo_acao, sucesso, duration)
        processados += 1

    return processados


def main():
    """Loop principal do serviço RPA de bloqueio de perfis."""
    print_startup_banner(SIGA_API_URL, POLLING_INTERVAL, POLLING_INTERVAL_IDLE)
    logger.info(f"Ambiente da API: {API_ENV.upper()} -> {SIGA_API_URL}")

    # Inicializar cliente da API
    cliente = SigaApiClient(SIGA_API_URL, SIGA_EMAIL, SIGA_PASSWORD)

    # Testar autenticação antes de entrar no loop
    try:
        cliente.autenticar()
        logger.info("Autenticação inicial com a API SIGA: OK")
    except Exception as e:
        logger.critical(f"Falha na autenticação inicial: {e}")
        logger.critical("Verifique as credenciais em .env ou config.py e se a API está rodando.")
        sys.exit(1)

    # Inicializar gerenciador de sessão do browser
    session_manager = SaggestaoSessionManager()
    
    # Inicializar métricas
    metrics = MetricsCollector()
    last_metrics_log = time.time()
    METRICS_LOG_INTERVAL = 3600  # Logar métricas a cada 1 hora

    # Loop principal de polling
    try:
        while True:
            try:
                total_processados = 0

                # 1. Processar bloqueios
                total_processados += processar_pendentes(cliente, session_manager, "BLOQUEIO", metrics)

                # 2. Processar desbloqueios
                total_processados += processar_pendentes(cliente, session_manager, "DESBLOQUEIO", metrics)

                # 3. Keep-alive em ciclos ociosos (apenas se sessão já foi iniciada)
                if total_processados == 0:
                    try:
                        session_manager.ensure_ready()
                    except Exception as e:
                        logger.warning(f"Erro durante keep-alive/verificação de sessão: {e}")

                # 4. Sinal de vida
                print_heartbeat(total_processados)
                
                # 5. Log periódico de métricas
                if time.time() - last_metrics_log > METRICS_LOG_INTERVAL:
                    metrics.log_summary()
                    last_metrics_log = time.time()

                # 6. Aguardar próximo ciclo
                intervalo = POLLING_INTERVAL if total_processados > 0 else POLLING_INTERVAL_IDLE
                time.sleep(intervalo)

            except KeyboardInterrupt:
                raise

            except Exception as e:
                logger.error(f"Erro inesperado no ciclo de polling: {e}", exc_info=True)
                logger.info(f"Aguardando {POLLING_INTERVAL}s antes de tentar novamente...")
                time.sleep(POLLING_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Interrupção pelo usuário (Ctrl+C).")
        metrics.log_summary() # Logar métricas finais no shutdown
    finally:
        print_shutdown_banner()
        session_manager.shutdown()


if __name__ == "__main__":
    main()
