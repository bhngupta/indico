# This file is part of Indico.
# Copyright (C) 2002 - 2025 CERN
#
# Indico is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see the
# LICENSE file for more details.

from sqlalchemy.ext.declarative import declared_attr

from indico.core.db import db
from indico.core.db.sqlalchemy.principals import PrincipalPermissionsMixin
from indico.core.db.sqlalchemy.util.models import auto_table_args
from indico.util.string import format_repr


class SessionPrincipal(PrincipalPermissionsMixin, db.Model):
    __tablename__ = 'session_principals'
    principal_backref_name = 'in_session_acls'
    principal_for = 'Session'
    unique_columns = ('session_id',)
    disallowed_protection_modes = frozenset()
    allow_emails = True
    allow_event_roles = True
    allow_category_roles = True
    allow_registration_forms = True

    @declared_attr
    def __table_args__(cls):
        return auto_table_args(cls, schema='events')

    #: The ID of the acl entry
    id = db.Column(
        db.Integer,
        primary_key=True
    )
    #: The ID of the associated session
    session_id = db.Column(
        db.Integer,
        db.ForeignKey('events.sessions.id'),
        nullable=False,
        index=True
    )

    # relationship backrefs:
    # - session (Session.acl_entries)

    def __repr__(self):
        return format_repr(self, 'id', 'session_id', 'principal', read_access=False, full_access=False, permissions=[])
