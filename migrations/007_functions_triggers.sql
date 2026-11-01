-- Stored function: restriction and trade exposure of one actor over a period.
CREATE FUNCTION actor_exposure(p_actor TEXT, p_from INT, p_to INT, p_include_synthetic BOOLEAN DEFAULT TRUE)
RETURNS TABLE (
    actor_code TEXT, exports_usd_millions NUMERIC, imports_usd_millions NUMERIC,
    controlled_trade_share_pct NUMERIC, restrictions_imposed BIGINT, restrictions_received BIGINT,
    avg_severity_received NUMERIC, est_impact_received_usd_bn NUMERIC
)
LANGUAGE sql STABLE AS $$
    WITH t AS (
        SELECT
            COALESCE(SUM(trade_value_usd_millions) FILTER (WHERE exporter_actor_code = p_actor), 0) AS ex,
            COALESCE(SUM(trade_value_usd_millions) FILTER (WHERE importer_actor_code = p_actor), 0) AS im,
            COALESCE(SUM(trade_value_usd_millions) FILTER (WHERE export_control_applied), 0) AS ctl,
            COALESCE(SUM(trade_value_usd_millions), 0) AS tot
        FROM trade_flow
        WHERE (exporter_actor_code = p_actor OR importer_actor_code = p_actor)
          AND year BETWEEN p_from AND p_to AND (p_include_synthetic OR NOT is_synthetic)
    ), r AS (
        SELECT
            COUNT(*) FILTER (WHERE imposing_actor_code = p_actor) AS imposed,
            COUNT(*) FILTER (WHERE target_actor_code = p_actor) AS received,
            AVG(severity_level) FILTER (WHERE target_actor_code = p_actor) AS sev,
            COALESCE(SUM(economic_impact_usd_bn_est) FILTER (WHERE target_actor_code = p_actor), 0) AS impact
        FROM restriction_measure
        WHERE (imposing_actor_code = p_actor OR target_actor_code = p_actor)
          AND EXTRACT(YEAR FROM date_implemented) BETWEEN p_from AND p_to
          AND (p_include_synthetic OR NOT is_synthetic)
    )
    SELECT p_actor, t.ex, t.im,
           CASE WHEN t.tot > 0 THEN ROUND(100 * t.ctl / t.tot, 2) ELSE 0 END,
           r.imposed, r.received, ROUND(r.sev, 2), r.impact
    FROM t, r;
$$;

-- Generic audit trigger for app-owned tables. The API sets app.user_id per transaction.
CREATE FUNCTION audit_row_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_user INT := NULLIF(current_setting('app.user_id', TRUE), '')::INT;
    v_pk TEXT := TG_ARGV[0];
BEGIN
    INSERT INTO audit_log (table_name, operation, row_pk, old_row, new_row, acting_user_id)
    VALUES (
        TG_TABLE_NAME, TG_OP,
        CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ->> v_pk ELSE to_jsonb(NEW) ->> v_pk END,
        CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE to_jsonb(OLD) END,
        CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE to_jsonb(NEW) END,
        v_user
    );
    RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER annotation_audit AFTER INSERT OR UPDATE OR DELETE ON annotation
    FOR EACH ROW EXECUTE FUNCTION audit_row_change('annotation_id');
CREATE TRIGGER alias_audit AFTER INSERT OR UPDATE OR DELETE ON supplier_company_alias
    FOR EACH ROW EXECUTE FUNCTION audit_row_change('alias_id');

-- Separation of duties spans a row and a user's role, which a CHECK cannot express.
CREATE FUNCTION alias_review_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status <> 'proposed' THEN
        IF NEW.reviewed_by = NEW.proposed_by THEN
            RAISE EXCEPTION 'alias % cannot be reviewed by its proposer', NEW.alias_id USING ERRCODE = 'check_violation';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM app_user WHERE user_id = NEW.reviewed_by AND role = 'admin' AND is_active) THEN
            RAISE EXCEPTION 'alias % must be reviewed by an active administrator', NEW.alias_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER alias_review_guard BEFORE INSERT OR UPDATE ON supplier_company_alias
    FOR EACH ROW EXECUTE FUNCTION alias_review_guard();

CREATE FUNCTION touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at := now(); RETURN NEW; END $$;
CREATE TRIGGER annotation_touch BEFORE UPDATE ON annotation
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- Stored procedure: review many aliases as one unit, so a bad item leaves nothing half-applied.
CREATE PROCEDURE review_aliases(p_alias_ids BIGINT[], p_decision TEXT, p_reviewer INT)
LANGUAGE plpgsql AS $$
DECLARE
    v_id BIGINT;
    v_found INT;
BEGIN
    IF p_decision NOT IN ('approved','rejected') THEN
        RAISE EXCEPTION 'invalid decision %', p_decision USING ERRCODE = 'check_violation';
    END IF;
    FOREACH v_id IN ARRAY p_alias_ids LOOP
        UPDATE supplier_company_alias
           SET status = p_decision, reviewed_by = p_reviewer, reviewed_at = now()
         WHERE alias_id = v_id AND status = 'proposed';
        GET DIAGNOSTICS v_found = ROW_COUNT;
        IF v_found = 0 THEN
            RAISE EXCEPTION 'alias % does not exist or was already reviewed', v_id USING ERRCODE = 'no_data_found';
        END IF;
    END LOOP;
END $$;
