import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'client'))

import threading, time, argparse, logging, json, random
from datetime import datetime

import grpc
import scoreboard_pb2 as pb2
import scoreboard_pb2_grpc as pb2_grpc
from client import ScoreboardClient

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(name)-12s] %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("TEST")


class TestResults:
    def __init__(self):
        self._lock   = threading.Lock()
        self.players = {}
        self.errors  = []

    def record(self, player_id: str, client: ScoreboardClient):
        with self._lock:
            self.players[player_id] = {
                "attempts": client.total_attempts, "success": client.total_success,
                "conflicts": client.total_conflicts, "rejected": client.total_rejected}

    def record_error(self, player_id: str, error: str):
        with self._lock:
            self.errors.append({"player": player_id, "error": error})

    def summary(self) -> dict:
        totals = {
            "players":   len(self.players),
            "attempts":  sum(p["attempts"]  for p in self.players.values()),
            "success":   sum(p["success"]   for p in self.players.values()),
            "conflicts": sum(p["conflicts"] for p in self.players.values()),
            "rejected":  sum(p["rejected"]  for p in self.players.values()),
            "errors":    len(self.errors),
        }
        if totals["attempts"] > 0:
            totals["conflict_rate"] = f"{100*totals['conflicts']/totals['attempts']:.1f}%"
            totals["success_rate"]  = f"{100*totals['success']/totals['attempts']:.1f}%"
        return totals


def player_worker(server_addr, player_id, game_id, rounds, min_pts, max_pts,
                  think_time, results, barrier):
    try:
        client = ScoreboardClient(server_addr, player_id, game_id)
        barrier.wait()
        client.play(rounds=rounds, min_pts=min_pts, max_pts=max_pts,
                    think_time=think_time)
        results.record(player_id, client)
    except Exception as e:
        log.error("Erro no player %s: %s", player_id, e)
        results.record_error(player_id, str(e))


def run_test(server_addr, n_players, game_id, rounds, min_pts, max_pts,
             think_time, instance_id):
    log.info("TESTE DE CONCORRÊNCIA - %d jogadores, %d rodadas", n_players, rounds)
    log.info("Servidor: %s  |  Instância: %s", server_addr, instance_id)

    results = TestResults()
    barrier = threading.Barrier(n_players)
    threads = [threading.Thread(
        target=player_worker,
        args=(server_addr, f"{instance_id}-P{i:02d}", game_id,
              rounds, min_pts, max_pts, think_time, results, barrier),
        daemon=True) for i in range(1, n_players + 1)]

    start = time.time()
    for t in threads: t.start()
    for t in threads: t.join(timeout=300)
    elapsed = time.time() - start

    channel = grpc.insecure_channel(server_addr)
    stub    = pb2_grpc.ScoreboardServiceStub(channel)
    final   = stub.GetScore(pb2.GetScoreRequest(game_id=game_id))
    summary = results.summary()

    log.info("RESULTADO FINAL - %.2fs", elapsed)
    log.info("  Escore final     : %d  (versão %d)", final.score, final.version)
    log.info("  Tentativas       : %d", summary["attempts"])
    log.info("  Sucessos         : %s  (%s)", summary["success"],
             summary.get("success_rate", "?"))
    log.info("  Conflitos OCC    : %s  (%s)", summary["conflicts"],
             summary.get("conflict_rate", "?"))
    log.info("  Erros            : %d", summary["errors"])

    out_file = f"result_{instance_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_file, "w") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "instance_id": instance_id,
            "server": server_addr, "game_id": game_id, "elapsed_s": round(elapsed, 2),
            "final_score": final.score, "final_version": final.version,
            "summary": summary, "per_player": results.players,
            "errors": results.errors}, f, indent=2)
    log.info("Resultado salvo em: %s", out_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server",      default="localhost:50051")
    parser.add_argument("--players",     type=int,   default=5)
    parser.add_argument("--game",        default="game1")
    parser.add_argument("--rounds",      type=int,   default=10)
    parser.add_argument("--min-pts",     type=int,   default=10)
    parser.add_argument("--max-pts",     type=int,   default=100)
    parser.add_argument("--think",       type=float, default=0.2)
    parser.add_argument("--instance-id", default="local")
    args = parser.parse_args()
    run_test(args.server, args.players, args.game, args.rounds,
             args.min_pts, args.max_pts, args.think, args.instance_id)
