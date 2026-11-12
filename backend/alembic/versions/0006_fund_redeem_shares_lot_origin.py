"""场外基金 M3：赎回申请份额、持仓批次来源扩展、申购金额可空

- fund_order_details 增加 apply_shares（赎回申请份额 / 红利再投资预计份额）
- fund_order_details.apply_amount 改为可空：赎回/红利再投资在确认前没有实际扣款金额（不猜测）
- position_lots.lot_origin 允许 FUND 与 DIVIDEND_REINVEST

Revision ID: 0006
Revises: 0005
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE fund_order_details
            ADD COLUMN apply_shares NUMERIC(20, 6);
        ALTER TABLE fund_order_details
            ALTER COLUMN apply_amount DROP NOT NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE position_lots
            DROP CONSTRAINT position_lots_lot_origin_check;
        ALTER TABLE position_lots
            ADD CONSTRAINT position_lots_lot_origin_check
            CHECK (lot_origin IN (
                'TRADE', 'OPENING_BALANCE', 'CORPORATE_ACTION',
                'FUND', 'DIVIDEND_REINVEST'));
        """
    )


def downgrade() -> None:
    # 赎回/红利再投资的 apply_amount 为空，降级时用其确认金额回填再恢复 NOT NULL。
    op.execute(
        """
        UPDATE fund_order_details d
           SET apply_amount = c.confirmed_amount
          FROM fund_confirmations c
         WHERE c.transaction_id = d.transaction_id AND d.apply_amount IS NULL;
        UPDATE fund_order_details SET apply_amount = 1 WHERE apply_amount IS NULL;
        ALTER TABLE fund_order_details
            ALTER COLUMN apply_amount SET NOT NULL;
        ALTER TABLE fund_order_details
            DROP COLUMN apply_shares;
        """
    )
    op.execute(
        """
        ALTER TABLE position_lots
            DROP CONSTRAINT position_lots_lot_origin_check;
        ALTER TABLE position_lots
            ADD CONSTRAINT position_lots_lot_origin_check
            CHECK (lot_origin IN (
                'TRADE', 'OPENING_BALANCE', 'CORPORATE_ACTION'));
        """
    )
