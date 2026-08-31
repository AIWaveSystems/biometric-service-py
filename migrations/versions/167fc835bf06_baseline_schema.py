"""baseline schema

Revision ID: 167fc835bf06
Revises:
Create Date: 2026-08-24 16:10:27.807455

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '167fc835bf06'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('api_clients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('scopes', sa.String(length=255), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.String(length=100), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_api_clients_key_prefix'), 'api_clients', ['key_prefix'], unique=True)
    op.create_index(op.f('ix_api_clients_name'), 'api_clients', ['name'], unique=True)
    op.create_index(op.f('ix_api_clients_uuid'), 'api_clients', ['uuid'], unique=True)
    op.create_table('portal_users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.Uuid(), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('is_bootstrap', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portal_users_username'), 'portal_users', ['username'], unique=True)
    op.create_index(op.f('ix_portal_users_uuid'), 'portal_users', ['uuid'], unique=True)
    op.create_table('voice_challenges',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('digits', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_voice_challenges_created_at'), 'voice_challenges', ['created_at'], unique=False)
    op.create_index(op.f('ix_voice_challenges_token'), 'voice_challenges', ['token'], unique=True)
    op.create_index(op.f('ix_voice_challenges_username'), 'voice_challenges', ['username'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.Uuid(), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('api_client_id', sa.Integer(), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['api_client_id'], ['api_clients.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('api_client_id', 'username', name='uq_users_tenant_username')
    )
    op.create_index(op.f('ix_users_api_client_id'), 'users', ['api_client_id'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=False)
    op.create_index(op.f('ix_users_uuid'), 'users', ['uuid'], unique=True)
    op.create_index('uq_users_portal_username', 'users', ['username'], unique=True, postgresql_where=sa.text('api_client_id IS NULL'), sqlite_where=sa.text('api_client_id IS NULL'))
    op.create_table('face_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('algorithm', sa.String(length=50), nullable=False),
    sa.Column('features', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_face_templates_user_id'), 'face_templates', ['user_id'], unique=False)
    op.create_table('voice_digit_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('digit', sa.String(length=2), nullable=False),
    sa.Column('n_components', sa.Integer(), nullable=False),
    sa.Column('parameters', sa.LargeBinary(), nullable=False),
    sa.Column('cmvn', sa.LargeBinary(), nullable=True),
    sa.Column('n_frames', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'digit', name='uq_voice_digit_user')
    )
    op.create_index(op.f('ix_voice_digit_templates_digit'), 'voice_digit_templates', ['digit'], unique=False)
    op.create_index(op.f('ix_voice_digit_templates_user_id'), 'voice_digit_templates', ['user_id'], unique=False)
    op.create_table('voice_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('algorithm', sa.String(length=50), nullable=False),
    sa.Column('n_components', sa.Integer(), nullable=False),
    sa.Column('parameters', sa.LargeBinary(), nullable=False),
    sa.Column('features', sa.LargeBinary(), nullable=False),
    sa.Column('embedding', sa.LargeBinary(), nullable=True),
    sa.Column('self_score', sa.Float(), nullable=False),
    sa.Column('self_sigma', sa.Float(), nullable=False),
    sa.Column('duration_seconds', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_voice_templates_user_id'), 'voice_templates', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_voice_templates_user_id'), table_name='voice_templates')
    op.drop_table('voice_templates')
    op.drop_index(op.f('ix_voice_digit_templates_user_id'), table_name='voice_digit_templates')
    op.drop_index(op.f('ix_voice_digit_templates_digit'), table_name='voice_digit_templates')
    op.drop_table('voice_digit_templates')
    op.drop_index(op.f('ix_face_templates_user_id'), table_name='face_templates')
    op.drop_table('face_templates')
    op.drop_index('uq_users_portal_username', table_name='users', postgresql_where=sa.text('api_client_id IS NULL'), sqlite_where=sa.text('api_client_id IS NULL'))
    op.drop_index(op.f('ix_users_uuid'), table_name='users')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_api_client_id'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_voice_challenges_username'), table_name='voice_challenges')
    op.drop_index(op.f('ix_voice_challenges_token'), table_name='voice_challenges')
    op.drop_index(op.f('ix_voice_challenges_created_at'), table_name='voice_challenges')
    op.drop_table('voice_challenges')
    op.drop_index(op.f('ix_portal_users_uuid'), table_name='portal_users')
    op.drop_index(op.f('ix_portal_users_username'), table_name='portal_users')
    op.drop_table('portal_users')
    op.drop_index(op.f('ix_api_clients_uuid'), table_name='api_clients')
    op.drop_index(op.f('ix_api_clients_name'), table_name='api_clients')
    op.drop_index(op.f('ix_api_clients_key_prefix'), table_name='api_clients')
    op.drop_table('api_clients')
