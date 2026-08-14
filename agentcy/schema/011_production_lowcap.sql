-- The Low-Cap Desk's selection state (docs/plans/2026-08-14-low-cap-desk-design.md).
-- A NEW table rather than a retrofit of production_top_member: that table's
-- UNIQUE(run_id, rank) would collide with a second lane's rank sequence, and its
-- append-only triggers forbid any alteration — append-only is achieved by adding
-- tables, never changing existing ones (invariant 10).
--
-- One row per (run, lens, name): the four lenses are separate ranked lists that are
-- never merged, so `lens` is part of the identity and rank uniqueness holds per lens.
-- forge_verdict rides along because Watch/Unknown names stay listable with their
-- verdict visible; Forged-out names never reach this table.

CREATE TABLE production_lowcap_member (
    run_id TEXT NOT NULL REFERENCES production_run(run_id),
    lens TEXT NOT NULL CHECK (lens IN ('graham', 'garp', 'downside', 'compounder')),
    security_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank > 0),
    forge_verdict TEXT NOT NULL CHECK (
        forge_verdict IN ('Survivor', 'Watch', 'Unknown')),
    PRIMARY KEY (run_id, lens, security_key),
    UNIQUE (run_id, lens, rank)
);

CREATE TRIGGER production_lowcap_member_no_update
BEFORE UPDATE ON production_lowcap_member
BEGIN SELECT RAISE(ABORT, 'production_lowcap_member is append-only'); END;

CREATE TRIGGER production_lowcap_member_no_delete
BEFORE DELETE ON production_lowcap_member
BEGIN SELECT RAISE(ABORT, 'production_lowcap_member is append-only'); END;
