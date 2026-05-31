# (ASR-12): Exclusão Mútua
# Scoreboard Distribuído — gRPC

Sistema de manutenção de escore para jogos multi-player, implementado com **gRPC + Python**.

---

## Controle de Concorrência: OCC (Optimistic Concurrency Control)

1. Cliente chama `GetScore` -> recebe `{score, version}`
2. Calcula `new_score = score + pontos_ganhos`
3. Chama `UpdateScore(new_score, base_version=version)`
4. Servidor verifica:
   - `base_version == versão_atual` -> aceita e incrementa versão
   - `base_version != versão_atual` -> **conflito**, retorna erro
   - `new_score <= score_atual`    -> **rejeição** (regra de negócio)
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
# Gerar os arquivos proto
python -m grpc_tools.protoc -I proto \
    --python_out=. --grpc_python_out=. \
    proto/scoreboard.proto
```

---

### Instância do Servidor

```bash
# Copie os .py gerados para server/
cp scoreboard_pb2*.py server/

python3 server/server.py --host 0.0.0.0 --port 5678
```

### Instâncias dos Clientes (repetir para cada)

```bash
# Em cada instância cliente:
cp scoreboard_pb2*.py client/ tests/

# Cliente único:
python client/client.py \
    --server 44.202.179.145:5678 \
    --player Player1 \
    --game game1 \
    --rounds 20

# Teste de concorrência (N clientes na mesma instância):
python tests/test_concurrent.py \
    --server 44.202.179.145:5678 \
    --players 10 \
    --rounds 20 \
    --instance-id aws-client-1
```

---


## Protocolo gRPC Definido

```protobuf
service ScoreboardService {
  rpc GetScore    (GetScoreRequest)    returns (GetScoreResponse);
  rpc UpdateScore (UpdateScoreRequest) returns (UpdateScoreResponse);
}
```
