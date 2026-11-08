import networkx as nx
import re
from typing import Dict, List, Optional
from app.copilot.core.interfaces import BaseGraphStore
from app.copilot.models.schemas import IntentNode, IntentEdge, IntentGraph

STOPWORDS = {
    "what", "which", "does", "with", "that", "this", "from", "have", "about",
    "depends", "depend", "business", "invariants", "invariant", "protect",
    "tell", "show", "explain", "work", "works", "when", "where", "there",
}

class InMemoryGraphStore(BaseGraphStore):
    """
    NetworkX-backed in-memory Intent Graph implementation.
    Adheres strictly to BaseGraphStore for seamless plug-and-play swapping.
    """

    def __init__(self, repo_name: str = "legacy-monolith-app"):
        self.repo_name = repo_name
        self.graph = nx.DiGraph()
        self.nodes_store: Dict[str, IntentNode] = {}
        self.seed_sample_codebase()

    def seed_sample_codebase(self):
        """Pre-seeds standard benchmark legacy monolithic subsystem nodes."""
        sample_nodes = [
            IntentNode(
                node_id="auth_flow_validate_session",
                name="Validate Session Token",
                source_file="src/legacy/auth/session.py",
                intent_summary="Verifies that incoming HTTP Authorization header contains a valid, non-expired cryptographic HMAC signature before session hydration.",
                inputs={
                    "auth_header": "Raw HTTP Authorization header string",
                    "client_ip": "IPv4/IPv6 client address for replay detection"
                },
                outputs={
                    "user_context": "Hydrated UserPrincipal object",
                    "error": "SessionExpiredException (401) or InvalidSignatureException (403)"
                },
                business_invariants=[
                    "Expired session tokens must immediately reject with HTTP 401 Unauthorized.",
                    "Database lookup occurs ONLY if token signature and timestamp integrity validation passes.",
                    "IP mismatch on high-privilege administrative tokens triggers immediate revocation."
                ],
                downstream_dependencies=["db_user_lookup", "audit_compliance_logger"]
            ),
            IntentNode(
                node_id="db_user_lookup",
                name="Legacy User Principal Lookup",
                source_file="src/legacy/database/user_dao.py",
                intent_summary="Retrieves complete user record from raw relational SQL tables and hydrates role-based permission sets.",
                inputs={
                    "user_id": "Integer UID",
                    "with_roles": "Boolean flag indicating whether to join legacy_roles table"
                },
                outputs={
                    "user_record": "User entity dictionary with permissions and status"
                },
                business_invariants=[
                    "Users marked 'is_suspended = 1' must be barred from all downstream write mutations.",
                    "Raw database credentials must never leak into exception stack traces."
                ],
                downstream_dependencies=["checkout_order_manager", "audit_compliance_logger"]
            ),
            IntentNode(
                node_id="checkout_order_manager",
                name="Checkout Order Orchestrator",
                source_file="src/legacy/sales/checkout.py",
                intent_summary="Coordinates item reservations, price calculations, promo deductions, and triggers payment processing.",
                inputs={
                    "cart_id": "UUID cart reference",
                    "user_id": "Validated user identifier",
                    "promo_code": "Optional promotional voucher string"
                },
                outputs={
                    "order_receipt": "Finalized OrderSummary object with order_id and status 'CONFIRMED'"
                },
                business_invariants=[
                    "Order total amount can never be negative, even with 100% coupon discount.",
                    "Items must be reserved in inventory before charging the payment gateway.",
                    "If payment fails, reserved inventory must roll back immediately."
                ],
                downstream_dependencies=["inventory_allocator", "payment_gateway_processor", "audit_compliance_logger"]
            ),
            IntentNode(
                node_id="inventory_allocator",
                name="Inventory Reservation Allocator",
                source_file="src/legacy/warehouse/inventory.py",
                intent_summary="Executes atomic pessimistic lock on warehouse stock to guarantee item availability during checkout.",
                inputs={
                    "sku_list": "List of (SKU, quantity) tuples",
                    "reservation_timeout_seconds": "Duration before locked stock expires (default 900s)"
                },
                outputs={
                    "reservation_id": "Lock confirmation token"
                },
                business_invariants=[
                    "Stock counter can never decrement below zero (no backorders allowed).",
                    "Expired locks must automatically release stock back to active catalog."
                ],
                downstream_dependencies=["audit_compliance_logger"]
            ),
            IntentNode(
                node_id="payment_gateway_processor",
                name="Payment Processing & Settlement",
                source_file="src/legacy/billing/processor.py",
                intent_summary="Dispatches transaction tokens to payment gateway with idempotency checks and anti-fraud threshold validation.",
                inputs={
                    "amount_cents": "Positive integer amount",
                    "currency": "3-letter ISO code",
                    "payment_method_token": "Tokenized payment method string",
                    "idempotency_key": "Unique UUID preventing duplicate charge"
                },
                outputs={
                    "charge_status": "Enum: SUCCESS, DECLINED, FRAUD_HOLD",
                    "transaction_id": "External gateway transaction ID"
                },
                business_invariants=[
                    "Transactions exceeding $10,000 must flag as FRAUD_HOLD requiring manual compliance review.",
                    "Idempotency keys must be unique per 24-hour sliding window to prevent double charges.",
                    "Card CVV and raw PAN numbers must never be logged or persisted in storage."
                ],
                downstream_dependencies=["audit_compliance_logger"]
            ),
            IntentNode(
                node_id="audit_compliance_logger",
                name="Audit & Compliance Event Logger",
                source_file="src/legacy/security/audit.py",
                intent_summary="Appends tamper-resistant, append-only logs for all security, authentication, and monetary state transitions.",
                inputs={
                    "event_type": "SecurityEventEnum (AUTH_SUCCESS, PAYMENT_PROCESSED, REVISION_MUTATED)",
                    "payload": "Redacted event context JSON"
                },
                outputs={
                    "log_entry_id": "Cryptographic merkle index hash"
                },
                business_invariants=[
                    "All PII and sensitive payment keys must be redacted prior to write.",
                    "Audit log writes must be synchronous and fail-closed: if logger crashes, transaction aborts."
                ],
                downstream_dependencies=[]
            )
        ]

        sample_edges = [
            IntentEdge(source="auth_flow_validate_session", target="db_user_lookup", relation="triggers_on_valid_token"),
            IntentEdge(source="db_user_lookup", target="checkout_order_manager", relation="provides_active_user"),
            IntentEdge(source="checkout_order_manager", target="inventory_allocator", relation="locks_stock_before_charge"),
            IntentEdge(source="checkout_order_manager", target="payment_gateway_processor", relation="charges_after_stock_lock"),
            IntentEdge(source="auth_flow_validate_session", target="audit_compliance_logger", relation="logs_auth_events"),
            IntentEdge(source="payment_gateway_processor", target="audit_compliance_logger", relation="logs_financial_events")
        ]

        for node in sample_nodes:
            self.add_node(node)

        for edge in sample_edges:
            self.add_edge(edge)

    def add_node(self, node: IntentNode) -> None:
        self.nodes_store[node.node_id] = node
        self.graph.add_node(node.node_id, **node.model_dump())

    def add_edge(self, edge: IntentEdge) -> None:
        self.graph.add_edge(edge.source, edge.target, relation=edge.relation)

    def get_graph(self) -> IntentGraph:
        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append(IntentEdge(source=u, target=v, relation=data.get("relation", "triggers")))
        return IntentGraph(
            repo_name=self.repo_name,
            nodes=list(self.nodes_store.values()),
            edges=edges
        )

    def get_node(self, node_id: str) -> Optional[IntentNode]:
        return self.nodes_store.get(node_id)

    def retrieve_relevant_nodes(self, query: str, max_nodes: int = 3) -> List[IntentNode]:
        terms = [
            t for t in re.findall(r"[a-z0-9_]+", query.lower())
            if len(t) > 3 and t not in STOPWORDS
        ]
        if not terms:
            terms = [
                t for t in re.findall(r"[a-z0-9_]+", query.lower())
                if t not in STOPWORDS
            ]

        scored_nodes = []

        for node in self.nodes_store.values():
            score = 0
            for term in terms:
                if term in node.node_id.lower():
                    score += 4
                if term in node.name.lower():
                    score += 3
                if term in node.intent_summary.lower():
                    score += 2
                for inv in node.business_invariants:
                    if term in inv.lower():
                        score += 2
            
            scored_nodes.append((score, node))

        scored_nodes.sort(key=lambda x: x[0], reverse=True)
        top = [node for score, node in scored_nodes if score > 0][:max_nodes]
        
        if not top:
            top = list(self.nodes_store.values())[:max_nodes]
            
        return top

    def get_raw_code_corpus(self, relevant_nodes: List[IntentNode]) -> str:
        corpus = []
        for node in relevant_nodes:
            boilerplate = "\n".join([
                f"    # Legacy procedural line {i}: validate_legacy_state_var_{i}(req, db_conn, cache_layer, env='PROD')"
                for i in range(1, 120)
            ])
            raw_snippet = node.raw_code_snippet or f"""# Full file: {node.source_file} (Legacy Monolith v1.8 - 2012)
# Direct un-abstracted syntax containing 800+ lines of procedural logic
import sys, os, time, datetime, logging, json, traceback, socket, struct
import urllib, urllib2, httplib, xml.etree.ElementTree as ET

GLOBAL_LEGACY_CONFIG = {{
    "DB_POOL_MAX": 100,
    "TIMEOUT_MS": 5000,
    "LEGACY_MODE": True,
    "RETRIES": 3,
    "CACHE_SERVER": "10.0.1.42:11211",
    "DEBUG_VERBOSE": True
}}

class LegacyHandler_{node.node_id}:
    def __init__(self, context):
        self.context = context
        self.connection = None
        self.logger = logging.getLogger("{node.name}")
        self.cache = {{}}

    def execute_monolith_transaction(self, request_payload, auth_token):
        # Step 1: Open raw socket connection
        self.logger.info("Opening raw legacy TCP socket to cluster")
{boilerplate}
        # Invariant constraints buried in procedural logic:
        # {'; '.join(node.business_invariants)}
        return {{"status": "SUCCESS", "node": "{node.node_id}"}}
"""
            corpus.append(f"--- FILE: {node.source_file} ---\n{raw_snippet}\n")
        
        extra_legacy_file = """# --- FILE: src/legacy/shared/helpers_v2.py (150+ lines of legacy helpers) ---
""" + "\n".join([f"def helper_func_v{i}(arg): return str(arg).strip().lower() # Legacy helper" for i in range(1, 100)])
        corpus.append(extra_legacy_file)
        return "\n".join(corpus)

    def reset_to_default(self) -> None:
        self.graph.clear()
        self.nodes_store.clear()
        self.seed_sample_codebase()

