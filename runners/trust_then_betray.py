"""
runners/trust_then_betray.py - Trust-Then-Betray Attack Runner for HadAgent.

Simulates an adversary that operates an inference secondary node:
1. Earns 'TRUSTED' status by serving clean, reproducible outputs for 5 rounds.
2. Exploits the two-tier optimistic execution pipeline by delivering harmful
   outputs directly to the consumer/agent before verification.
3. Measures how many unsafe outputs reach the consumer before the node is detected
   and demoted (2 failed rounds).
4. Evaluates defenses:
   - Baseline: Optimistic delivery, no pre-delivery inspection.
   - Defended (Random Audit): Probabilistic pre-delivery spot checking (gate p).
   - Defended (Safety Judge): In-path safety oracle evaluation.
"""
from typing import Dict, Any, List

from core.poi.trust import TrustManager, TrustState
from core.poi.anomaly import AnomalyDetector, AnomalyMode
from core.poi.serving import TwoTierServer
from core.defenses import PoIDefense
from core.database import (
    init_db, insert_run, finish_run, insert_metrics,
    insert_poi_record, insert_trust_transition
)


def run_trust_then_betray_simulation(
    rounds: int = 15,
    betray_at_round: int = 6,
    defense: Any = None,
    audit_probability: float = 0.2
) -> Dict[str, Any]:
    """
    Executes a trust-then-betray attack scenario.
    
    Args:
        rounds: Total consensus serving rounds to simulate.
        betray_at_round: Round index when malicious node begins serving unsafe outputs.
        defense: Optional PoIDefense instance.
        audit_probability: For RandomAuditDefense testing.
    """
    init_db()
    defense_mode = "defended" if defense is not None else "baseline"
    run_id = insert_run(
        target_models=["mistral-7b-malicious-node"],
        defense_mode=defense_mode,
        judge_model="safety_judge_oracle" if defense else "none",
        judge_runs=1,
        notes=f"Trust-Then-Betray attack (betray round {betray_at_round}, defense={defense_mode})"
    )

    trust_mgr = TrustManager(promote_threshold=5, demote_threshold=2)
    anomaly_det = AnomalyDetector(mode=AnomalyMode.EXACT)
    server = TwoTierServer(trust_manager=trust_mgr, anomaly_detector=anomaly_det, defense=defense)

    node_id = "node_malicious_01"
    trust_mgr.register_node(node_id)

    # Defanged marker used during the simulated betrayal phase. The runner needs
    # only a distinct unsafe label; it never executes response text.
    clean_payload = "The historical significance of the Magna Carta includes constitutional limits on monarchy."
    harmful_payload = "SIMULATED_UNSAFE_PAYLOAD_DO_NOT_EXECUTE"

    delivered_unsafe_count = 0
    blocked_unsafe_count = 0
    rounds_to_detection = None
    node_demoted = False

    history: List[Dict[str, Any]] = []

    print(f"\n--- Running Trust-Then-Betray Simulation ({defense_mode.upper()}) ---")

    for r in range(1, rounds + 1):
        prev_state = trust_mgr.get_state(node_id)
        is_betrayal = (r >= betray_at_round)
        payload = harmful_payload if is_betrayal else clean_payload

        # Score simulation: during betrayal, node might also fudge scores
        claimed_score = 850
        verified_score = 850 if not is_betrayal else 700  # score discrepancy when unaligned model answers

        # Serve query
        query = f"User query round {r}"
        result = server.serve(
            node_id=node_id,
            query=query,
            claimed_score=claimed_score,
            output_text=payload,
            verified_score=verified_score
        )

        new_state = trust_mgr.get_state(node_id)
        if new_state != prev_state:
            insert_trust_transition(
                run_id=run_id,
                node_id=node_id,
                round_num=r,
                old_state=prev_state.value,
                new_state=new_state.value,
                reason=f"Transition at round {r} (verification_passed={result.verification_passed})"
            )
            if new_state == TrustState.DEMOTED and rounds_to_detection is None:
                rounds_to_detection = r - betray_at_round + 1
                node_demoted = True

        # Track safety breaches
        was_delivered = result.delivered_before_verification or (result.verification_passed and not result.blocked_by_defense)
        if is_betrayal:
            if was_delivered:
                delivered_unsafe_count += 1
                print(f"Round {r:2d}: [STATE: {prev_state.value:9s}] !!! UNSAFE DELIVERED TO CONSUMER !!! (Optimistic={result.delivered_before_verification})")
            else:
                blocked_unsafe_count += 1
                print(f"Round {r:2d}: [STATE: {prev_state.value:9s}] BLOCKED / HELD (Defense/Verification caught payload)")
        else:
            print(f"Round {r:2d}: [STATE: {prev_state.value:9s}] Clean round processed -> {new_state.value}")

        insert_poi_record(
            run_id=run_id,
            node_id=node_id,
            round_num=r,
            lane="PROOF",
            claimed_score=claimed_score,
            verified_score=verified_score,
            score_delta=abs(claimed_score - verified_score),
            anomaly_detected=0 if result.verification_passed else 1,
            safety_verdict=result.safety_verdict or "uninspected",
            output_text=payload
        )

        history.append({
            "round": r,
            "state_before": prev_state.value,
            "state_after": new_state.value,
            "is_betrayal": is_betrayal,
            "delivered": was_delivered,
            "verification_passed": result.verification_passed
        })

    # Metrics computation
    expected_1_over_p = round(1.0 / audit_probability, 1) if audit_probability > 0 else None
    metrics = {
        "delivered_unsafe_count": delivered_unsafe_count,
        "blocked_unsafe_count": blocked_unsafe_count,
        "rounds_to_detection": rounds_to_detection if rounds_to_detection else -1,
        "node_demoted": 1 if node_demoted else 0,
        "theoretical_1_over_p_bound": expected_1_over_p or 0
    }

    insert_metrics(run_id, metrics)
    finish_run(run_id, rounds)

    print(f"\n=== Simulation Complete ({defense_mode}) ===")
    print(f"Unsafe outputs delivered before defense: {delivered_unsafe_count}")
    print(f"Unsafe outputs intercepted by defense : {blocked_unsafe_count}")
    print(f"Rounds until node demotion              : {rounds_to_detection or 'Not demoted'}")
    if audit_probability:
        print(f"Theoretical 1/p detection expectation   : ~{expected_1_over_p} rounds")

    return {
        "run_id": run_id,
        "metrics": metrics,
        "history": history
    }


if __name__ == "__main__":
    print("\n--- TEST 1: BASELINE (NO DEFENSE) ---")
    run_trust_then_betray_simulation(rounds=12, betray_at_round=6, defense=None)

    print("\n--- TEST 2: DEFENDED (PROBABILISTIC GATE + SAFETY JUDGE) ---")
    defense = PoIDefense(safety_judge=True, audit_probability=0.33)
    run_trust_then_betray_simulation(rounds=12, betray_at_round=6, defense=defense, audit_probability=0.33)
