"""
Formatador de logs com cores para melhor visualização no terminal.
Compatível com Windows usando colorama.
"""

import logging
import sys

try:
    from colorama import Fore, Back, Style, init
    # Inicializa colorama para Windows
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False
    # Fallback: sem cores se colorama não estiver instalado
    class Fore:
        RESET = RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = WHITE = LIGHTBLACK_EX = ""
    class Back:
        RESET = ""
    class Style:
        RESET_ALL = BRIGHT = ""


class ColoredFormatter(logging.Formatter):
    """
    Formatador customizado que adiciona cores baseado no nível do log.
    """

    # Cores por nível de log
    LEVEL_COLORS = {
        'DEBUG': Fore.LIGHTBLACK_EX,      # Cinza claro
        'INFO': Fore.CYAN,                 # Ciano
        'WARNING': Fore.YELLOW,            # Amarelo
        'ERROR': Fore.RED,                 # Vermelho
        'CRITICAL': Fore.WHITE + Back.RED, # Branco com fundo vermelho
    }

    # Cores para palavras-chave específicas
    KEYWORD_COLORS = {
        'SUCESSO': Fore.GREEN + Style.BRIGHT,
        'FALHA': Fore.RED + Style.BRIGHT,
        'BLOQUEIO': Fore.MAGENTA + Style.BRIGHT,
        'DESBLOQUEIO': Fore.BLUE + Style.BRIGHT,
        'OK': Fore.GREEN + Style.BRIGHT,
        'ERRO': Fore.RED + Style.BRIGHT,
    }

    def __init__(self, fmt=None, datefmt=None, use_colors=True):
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors and COLORAMA_AVAILABLE

    def format(self, record):
        if not self.use_colors:
            return super().format(record)

        # Salva a mensagem original
        original_msg = record.msg

        # Formata a mensagem base
        formatted = super().format(record)

        # Aplica cor ao nível do log
        level_color = self.LEVEL_COLORS.get(record.levelname, '')

        # Substitui o levelname pela versão colorida
        if level_color:
            formatted = formatted.replace(
                record.levelname,
                f"{level_color}{record.levelname}{Style.RESET_ALL}"
            )

        # Aplica cores a palavras-chave específicas
        for keyword, color in self.KEYWORD_COLORS.items():
            if keyword in formatted:
                formatted = formatted.replace(
                    keyword,
                    f"{color}{keyword}{Style.RESET_ALL}"
                )

        # Destaca números de ID (ex: #1893)
        import re
        formatted = re.sub(
            r'(#\d+)',
            f"{Fore.YELLOW}\\1{Style.RESET_ALL}",
            formatted
        )

        # Destaca SIAPE
        formatted = re.sub(
            r'(SIAPE=\d+)',
            f"{Fore.CYAN + Style.BRIGHT}\\1{Style.RESET_ALL}",
            formatted
        )

        # Destaca códigos de unidade
        formatted = re.sub(
            r'(Unidade=\d+)',
            f"{Fore.MAGENTA}\\1{Style.RESET_ALL}",
            formatted
        )

        # Destaca separadores (===)
        formatted = re.sub(
            r'(={10,})',
            f"{Fore.BLUE + Style.BRIGHT}\\1{Style.RESET_ALL}",
            formatted
        )

        # Destaca o timestamp
        formatted = re.sub(
            r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})',
            f"{Fore.LIGHTBLACK_EX}\\1{Style.RESET_ALL}",
            formatted
        )

        return formatted


def setup_colored_logging(log_level=logging.INFO, log_file=None):
    """
    Configura logging com cores para o terminal e sem cores para arquivo.

    Args:
        log_level: Nível de log (logging.INFO, logging.DEBUG, etc)
        log_file: Caminho para arquivo de log (opcional)

    Returns:
        Logger raiz configurado
    """
    # Formato do log
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

    # Handler para console (COM CORES)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(ColoredFormatter(
        fmt=log_format,
        datefmt=date_format,
        use_colors=True
    ))

    # Configurar handlers
    handlers = [console_handler]

    # Handler para arquivo (SEM CORES)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter(
            fmt=log_format,
            datefmt=date_format
        ))
        handlers.append(file_handler)

    # Configurar logging básico
    logging.basicConfig(
        level=log_level,
        handlers=handlers
    )

    return logging.getLogger()


def print_startup_banner(siga_url, polling_active, polling_idle):
    """
    Imprime banner colorido de inicialização do serviço.
    """
    if not COLORAMA_AVAILABLE:
        # Fallback sem cores
        print("=" * 60)
        print("SERVIÇO RPA DE BLOQUEIO DE PERFIS - INICIANDO")
        print(f"API SIGA: {siga_url}")
        print(f"Polling ativo: {polling_active}s | Polling ocioso: {polling_idle}s")
        print("=" * 60)
        return

    print(f"\n{Fore.BLUE + Style.BRIGHT}{'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.GREEN + Style.BRIGHT}>> SERVICO RPA DE BLOQUEIO DE PERFIS - INICIANDO <<{Style.RESET_ALL}")
    print(f"{Fore.CYAN}API SIGA: {Fore.WHITE + Style.BRIGHT}{siga_url}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Polling ativo: {Fore.WHITE}{polling_active}s{Fore.CYAN} | Polling ocioso: {Fore.WHITE}{polling_idle}s{Style.RESET_ALL}")
    print(f"{Fore.BLUE + Style.BRIGHT}{'=' * 60}{Style.RESET_ALL}\n")


def print_shutdown_banner():
    """
    Imprime banner colorido de encerramento do serviço.
    """
    if not COLORAMA_AVAILABLE:
        print("\n" + "=" * 60)
        print("SERVIÇO ENCERRADO PELO USUÁRIO (Ctrl+C)")
        print("=" * 60)
        return

    print(f"\n{Fore.BLUE + Style.BRIGHT}{'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW + Style.BRIGHT}>> SERVICO ENCERRADO PELO USUARIO (Ctrl+C) <<{Style.RESET_ALL}")
    print(f"{Fore.BLUE + Style.BRIGHT}{'=' * 60}{Style.RESET_ALL}\n")


def print_heartbeat(total_processados=0):
    """
    Imprime sinal de vida do serviço com data/hora atual.

    Args:
        total_processados: Quantidade de itens processados no último ciclo
    """
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not COLORAMA_AVAILABLE:
        if total_processados > 0:
            print(f"[{timestamp}] Ciclo concluido: {total_processados} item(ns) processado(s)")
        else:
            print(f"[{timestamp}] Aguardando novos pedidos...")
        return

    if total_processados > 0:
        print(f"{Fore.GREEN}[{timestamp}]{Style.RESET_ALL} {Fore.CYAN}Ciclo concluido: {Fore.WHITE + Style.BRIGHT}{total_processados}{Style.RESET_ALL} {Fore.CYAN}item(ns) processado(s){Style.RESET_ALL}")
    else:
        print(f"{Fore.LIGHTBLACK_EX}[{timestamp}]{Style.RESET_ALL} {Fore.YELLOW}Aguardando novos pedidos...{Style.RESET_ALL}")
