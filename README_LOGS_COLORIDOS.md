# 🎨 Logs Coloridos - Documentação

## Visão Geral

O sistema de logs foi aprimorado com **cores** para facilitar a visualização e identificação rápida de informações importantes no terminal.

## Recursos

### Cores por Nível de Log
- **DEBUG**: Cinza claro - informações detalhadas
- **INFO**: Ciano - operações normais
- **WARNING**: Amarelo - avisos e atenções
- **ERROR**: Vermelho - erros
- **CRITICAL**: Branco com fundo vermelho - falhas graves

### Destaques Automáticos

O sistema destaca automaticamente:

1. **Palavras-chave**:
   - `SUCESSO` - Verde brilhante
   - `FALHA` - Vermelho brilhante
   - `BLOQUEIO` - Magenta brilhante
   - `DESBLOQUEIO` - Azul brilhante
   - `OK` - Verde brilhante
   - `ERRO` - Vermelho brilhante

2. **Identificadores**:
   - `#1893` - IDs de bloqueio em amarelo
   - `SIAPE=1960398` - SIAPE em ciano brilhante
   - `Unidade=23150521` - Códigos de unidade em magenta

3. **Elementos visuais**:
   - Separadores (`====`) em azul brilhante
   - Timestamps em cinza claro

## Instalação

A dependência `colorama` já foi adicionada ao `requirements.txt`:

```bash
pip install -r requirements.txt
```

Ou instale manualmente:

```bash
pip install colorama
```

## Uso

### Serviço RPA Principal

O sistema já está configurado automaticamente em `servico_rpa.py`:

```bash
python servico_rpa.py
```

### Scripts de Teste

Para visualizar exemplos de todos os tipos de logs coloridos:

```bash
python test_colors.py
```

Para testar o sinal de vida (heartbeat) do serviço:

```bash
python test_heartbeat.py
```

### Integração em Novos Módulos

```python
from colored_logger import setup_colored_logging
import logging

# Configurar logging com cores
setup_colored_logging(log_level=logging.INFO, log_file="app.log")

# Criar logger
logger = logging.getLogger("MeuModulo")

# Usar normalmente
logger.info("Operação normal")
logger.warning("Atenção necessária")
logger.error("Algo deu errado")
```

## Arquivos de Log

- **Terminal**: Logs com cores para visualização facilitada
- **Arquivo** (`servico_rpa.log`): Logs SEM cores para parsing e análise

## Compatibilidade

- ✅ Windows (usando colorama)
- ✅ Linux
- ✅ macOS

Se o `colorama` não estiver instalado, o sistema automaticamente desativa as cores e funciona normalmente.

## Exemplos de Saída

### Banner de Inicialização
```
============================================================
>> SERVICO RPA DE BLOQUEIO DE PERFIS - INICIANDO <<
API SIGA: http://localhost:8000
Polling ativo: 30s | Polling ocioso: 60s
============================================================
```

### Logs de Operação
```
[INFO] Encontrados 3 bloqueio(s) pendente(s).
[INFO] [BLOQUEIO #1893] Iniciando: SIAPE=1960398, Unidade=23150521
[INFO] [BLOQUEIO #1893] SUCESSO - Confirmado na API.
[WARNING] [BLOQUEIO #1894] FALHA - Servidor não encontrado
[ERROR] [BLOQUEIO #1895] ERRO ao confirmar na API: HTTP 500
```

### Sinal de Vida (Heartbeat)
A cada ciclo de polling, o sistema exibe um sinal de vida com timestamp:
```
[2026-02-13 20:50:11] Ciclo concluido: 1 item(ns) processado(s)
[2026-02-13 20:50:41] Aguardando novos pedidos...
[2026-02-13 20:51:11] Ciclo concluido: 3 item(ns) processado(s)
```

- **Verde**: Quando há processamento de itens
- **Amarelo claro**: Quando não há pendências

### Banner de Encerramento
```
============================================================
>> SERVICO ENCERRADO PELO USUARIO (Ctrl+C) <<
============================================================
```

## Personalização

Para ajustar as cores, edite o arquivo `colored_logger.py`:

```python
LEVEL_COLORS = {
    'DEBUG': Fore.LIGHTBLACK_EX,
    'INFO': Fore.CYAN,
    'WARNING': Fore.YELLOW,
    'ERROR': Fore.RED,
    'CRITICAL': Fore.WHITE + Back.RED,
}
```
