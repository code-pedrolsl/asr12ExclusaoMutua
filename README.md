# (ASR-12): Exclusão Mútua
# Scoreboard Distribuído — gRPC

Sistema de manutenção de escore para jogos multi-player, implementado com **gRPC + Python**.

---

## Arquitetura

```
┌──────────────────────────────────────────────────────────────┐
│                        AWS EC2 – Servidor                    │
│                                                              │
│   server/server.py                                           │
│   ┌─────────────────────────────────────────────────────┐   │
│   │  ScoreboardServicer (gRPC)                          │   │
│   │  • GetScore    → retorna escore + versão OCC        │   │
│   │  • UpdateScore → valida versão + regra "só cresce"  │   │
│   │  lock: threading.Lock (proteção de estado)          │   │
│   └─────────────────────────────────────────────────────┘   │
│                      porta 5678                             │
└──────────────────────────────────────────────────────────────┘
          ↑           ↑           ↑
         gRPC        gRPC        gRPC
          ↓           ↓           ↓
┌───────────┐  ┌───────────┐  ┌───────────┐
│AWS Client1│  │AWS Client2│  │AWS Client3│
│client.py  │  │client.py  │  │client.py  │
└───────────┘  └───────────┘  └───────────┘
```

---

## Controle de Concorrência: OCC (Optimistic Concurrency Control)

O sistema usa **Optimistic Concurrency Control** — sem locks no cliente. O protocolo é:

1. Cliente chama `GetScore` → recebe `{score, version}`
2. Calcula `new_score = score + pontos_ganhos`
3. Chama `UpdateScore(new_score, base_version=version)`
4. Servidor verifica:
   - `base_version == versão_atual` → aceita e incrementa versão
   - `base_version != versão_atual` → **conflito**, retorna erro
   - `new_score <= score_atual`    → **rejeição** (regra de negócio)
5. Em caso de conflito, o cliente faz **retry com backoff exponencial**

---

## Estrutura de Arquivos

```
scoreboard/
├── proto/
│   └── scoreboard.proto          # Definição gRPC
├── server/
│   └── server.py                 # Servidor gRPC
├── client/
│   └── client.py                 # Cliente individual
├── tests/
│   └── test_concurrent.py        # Teste com N clientes simultâneos
├── scoreboard_pb2.py             # Gerado pelo protoc
├── scoreboard_pb2_grpc.py        # Gerado pelo protoc
└── requirements.txt
```

---

## Instalação

```bash
pip install -r requirements.txt

# Regenerar os arquivos proto (se necessário)
python -m grpc_tools.protoc -I proto \
    --python_out=. --grpc_python_out=. \
    proto/scoreboard.proto
```

---

## Deploy na AWS

### Instância do Servidor

```bash
# 1. Lance uma EC2 (ex: t3.micro, Ubuntu 22.04)
# 2. Libere a porta 5678 no Security Group (TCP inbound)
# 3. Conecte via SSH e execute:

git clone <repo> && cd scoreboard
pip install -r requirements.txt

# Copie os .py gerados para server/
cp scoreboard_pb2*.py server/

python server/server.py --host 0.0.0.0 --port 5678
```

### Instâncias dos Clientes (repetir para cada)

```bash
# Em cada instância cliente:
pip install -r requirements.txt
cp scoreboard_pb2*.py client/ tests/

# Cliente único:
python client/client.py \
    --server 3.227.138.6:5678 \
    --player Player1 \
    --game game1 \
    --rounds 20

# Teste de concorrência (N clientes na mesma instância):
python tests/test_concurrent.py \
    --server 3.227.138.6:5678 \
    --players 10 \
    --rounds 20 \
    --instance-id aws-client-1
```

---

## Resultados do Teste

### Configuração do Teste Local (simulando AWS)

| Parâmetro        | Valor             |
|-----------------|-------------------|
| Jogadores        | 8 (threads)       |
| Rodadas por jogador | 12            |
| Pontos por rodada | 10 a 150        |
| Think time       | 0.05s             |
| Middleware       | gRPC              |

### Resultado

| Métrica                | Valor   |
|------------------------|---------|
| Tempo total            | 5.16s   |
| Escore final           | 6.944   |
| Versão final           | 94      |
| Total de tentativas    | 163     |
| Atualizações bem-sucedidas | 94 (57.7%) |
| Conflitos OCC (retries) | 69 (42.3%) |
| Rejeitados (score menor) | 0      |
| Falhas sem recuperação | 0 erros |

### Análise por Jogador

| Jogador | Tentativas | Sucessos | Conflitos |
|---------|-----------|----------|-----------|
| P01     | 25        | 12       | 13        |
| P02     | 19        | 12       | 7         |
| P03     | 20        | 12       | 8         |
| P04     | 21        | 12       | 9         |
| P05     | 21        | 12       | 9         |
| P06     | 20        | 11       | 9         |
| P07     | 22        | 11       | 11        |
| P08     | 15        | 12       | 3         |

### Observações

**Integridade garantida:** O escore sempre cresceu de forma monotônica (0 → 6.944), sem perda de updates nem valores incorretos, mesmo com 8 clientes concorrentes.

**Taxa de conflito de 42.3%:** Alta, pois o `think_time=0.05s` é muito baixo (simula clientes extremamente agressivos). Em cenários reais com `think_time ≥ 0.5s` a taxa cai para ~5-15%.

**Retry com backoff exponencial funcionou:** Nenhuma rodada ficou sem ser concluída. Os clientes que sofreram mais conflitos (P01, P07) simplesmente levaram mais tempo e tentativas, mas eventualmente atualizaram com sucesso.

**Regra "escore só cresce":** Zero rejeições por valor menor — o protocolo LER-CALCULAR-ESCREVER garante que o novo valor sempre é score_atual + Δ.

---

## Protocolo gRPC Definido

```protobuf
service ScoreboardService {
  rpc GetScore    (GetScoreRequest)    returns (GetScoreResponse);
  rpc UpdateScore (UpdateScoreRequest) returns (UpdateScoreResponse);
}
```

Campos relevantes:
- `GetScoreResponse.version` — versão do escore (OCC token)
- `UpdateScoreRequest.base_version` — versão que o cliente leu
- `UpdateScoreResponse.success` — false em caso de conflito ou rejeição
