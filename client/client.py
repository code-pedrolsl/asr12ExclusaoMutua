import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grpc, random, time, logging, argparse

import scoreboard_pb2 as pb2
import scoreboard_pb2_grpc as pb2_grpc

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")


class ScoreboardClient:
    MAX_RETRIES  = 5
    BASE_BACKOFF = 0.1

    def __init__(self, server_addr: str, player_id: str, game_id: str):
        self.player_id   = player_id
        self.game_id     = game_id
        self.log         = logging.getLogger(player_id)
        channel = grpc.insecure_channel(server_addr,
            options=[("grpc.keepalive_time_ms", 10000)])
        self.stub = pb2_grpc.ScoreboardServiceStub(channel)
        self.total_attempts  = 0
        self.total_conflicts = 0
        self.total_success   = 0
        self.total_rejected  = 0

    def get_score(self) -> pb2.GetScoreResponse:
        return self.stub.GetScore(pb2.GetScoreRequest(game_id=self.game_id))

    def update_score(self, points_gained: int) -> dict:
        for attempt in range(1, self.MAX_RETRIES + 1):
            self.total_attempts += 1

            current = self.get_score()

            new_score = current.score + points_gained
            time.sleep(random.uniform(0.01, 0.05))

            resp = self.stub.UpdateScore(pb2.UpdateScoreRequest(
                game_id=self.game_id, new_score=new_score,
                base_version=current.version, player_id=self.player_id))

            if resp.success:
                self.total_success += 1
                self.log.info(" Update  attempt=%d  +%d pts  score=%d  version=%d",
                    attempt, points_gained, resp.score, resp.version)
                return {"status": "ok", "score": resp.score, "attempts": attempt}

            if "Conflito" in resp.message:
                self.total_conflicts += 1
                backoff = self.BASE_BACKOFF * (2 ** (attempt - 1)) + random.uniform(0, 0.05)
                self.log.warning(" Conflito (tentativa %d/%d) -> retry em %.2fs",
                    attempt, self.MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue

            self.total_rejected += 1
            self.log.warning(" Rejeitado: %s", resp.message)
            return {"status": "rejected", "score": resp.score, "attempts": attempt}

        self.log.error(" Falha após %d tentativas", self.MAX_RETRIES)
        return {"status": "failed", "attempts": self.MAX_RETRIES}

    def play(self, rounds: int, min_pts: int = 10, max_pts: int = 100,
             think_time: float = 0.5):
        self.log.info(" Iniciando sessão: %d rodadas ", rounds)
        start = time.time()
        for r in range(1, rounds + 1):
            pts = random.randint(min_pts, max_pts)
            self.log.info(" Rodada %d/%d  pontos=%d ", r, rounds, pts)
            self.update_score(pts)
            if r < rounds:
                time.sleep(random.uniform(0, think_time))
        elapsed = time.time() - start
        self.log.info(" RESUMO: tentativas=%d sucessos=%d conflitos=%d (%.2fs) ",
            self.total_attempts, self.total_success, self.total_conflicts, elapsed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server",  default="localhost:50051")
    parser.add_argument("--player",  default="Player1")
    parser.add_argument("--game",    default="game1")
    parser.add_argument("--rounds",  type=int,   default=10)
    parser.add_argument("--min-pts", type=int,   default=10)
    parser.add_argument("--max-pts", type=int,   default=100)
    parser.add_argument("--think",   type=float, default=0.3)
    args = parser.parse_args()
    client = ScoreboardClient(args.server, args.player, args.game)
    client.play(rounds=args.rounds, min_pts=args.min_pts,
                max_pts=args.max_pts, think_time=args.think)
