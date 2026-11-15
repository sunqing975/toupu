"""Register local account metadata tool without replacing Agent customizations."""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO agent_skills
            (id, key, name, description, category, builtin, enabled, created_at)
        VALUES (gen_random_uuid(), 'create_account', '创建投谱账户',
                '创建账户资料，不是券商开户，不产生资金或持仓。', 'action', true, true, now())
        ON CONFLICT (key) DO NOTHING
    """)
    op.execute("""
        UPDATE agent_definitions
        SET enabled_skill_keys = enabled_skill_keys || '["create_account"]'::jsonb
        WHERE key = 'toupu-assistant' AND is_builtin = true
          AND NOT enabled_skill_keys @> '["create_account"]'::jsonb
    """)


def downgrade():
    op.execute("""
        UPDATE agent_definitions SET enabled_skill_keys = enabled_skill_keys - 'create_account'
    """)
    op.execute("DELETE FROM agent_skills WHERE key = 'create_account'")
