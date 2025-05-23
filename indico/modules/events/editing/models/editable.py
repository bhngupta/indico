# This file is part of Indico.
# Copyright (C) 2002 - 2025 CERN
#
# Indico is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see the
# LICENSE file for more details.

from sqlalchemy import orm
from sqlalchemy.event import listens_for
from sqlalchemy.orm import column_property
from sqlalchemy.sql import select

from indico.core.db import db
from indico.core.db.sqlalchemy import PyIntEnum
from indico.util.enum import RichIntEnum
from indico.util.i18n import _, orig_string, pgettext
from indico.util.locators import locator_property
from indico.util.string import format_repr
from indico.web.flask.util import url_for


class EditableType(RichIntEnum):
    __titles__ = [None, _('Paper'), _('Slides'), _('Poster')]
    __editor_permissions__ = [None, 'paper_editing', 'slides_editing', 'poster_editing']
    paper = 1
    slides = 2
    poster = 3

    @property
    def editor_permission(self):
        return self.__editor_permissions__[self]


class EditableState(RichIntEnum):
    __titles__ = [
        None,
        pgettext('Editable', 'New'),
        pgettext('Editable', 'Ready for Review'),
        pgettext('Editable', 'Needs Confirmation'),
        pgettext('Editable', 'Needs Changes'),
        pgettext('Editable', 'Accepted'),
        pgettext('Editable', 'Rejected'),
        pgettext('Editable', 'Accepted by Submitter'),
    ]
    __css_classes__ = [
        None,
        'highlight',
        'ready',
        'editing-make-changes',
        'editing-request-changes',
        'success',
        'editing-rejected',
        'editing-accepted-submitter',
    ]

    new = 1
    ready_for_review = 2
    needs_submitter_confirmation = 3
    needs_submitter_changes = 4
    accepted = 5
    rejected = 6
    accepted_submitter = 7


class Editable(db.Model):
    __tablename__ = 'editables'
    __table_args__ = (db.Index(None, 'contribution_id', 'type', unique=True,
                               postgresql_where=db.text('NOT is_deleted')),
                      {'schema': 'event_editing'})

    id = db.Column(
        db.Integer,
        primary_key=True
    )
    contribution_id = db.Column(
        db.ForeignKey('events.contributions.id'),
        index=True,
        nullable=False
    )
    type = db.Column(
        PyIntEnum(EditableType),
        nullable=False
    )
    editor_id = db.Column(
        db.ForeignKey('users.users.id'),
        index=True,
        nullable=True
    )
    published_revision_id = db.Column(
        db.ForeignKey('event_editing.revisions.id'),
        index=True,
        nullable=True
    )
    is_deleted = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
    )

    contribution = db.relationship(
        'Contribution',
        lazy=True,
        backref=db.backref(
            'editables',
            primaryjoin='(Editable.contribution_id == Contribution.id) & ~Editable.is_deleted',
            lazy=True,
        )
    )
    editor = db.relationship(
        'User',
        lazy=True,
        backref=db.backref(
            'editor_for_editables',
            lazy='dynamic'
        )
    )
    published_revision = db.relationship(
        'EditingRevision',
        foreign_keys=published_revision_id,
        lazy=True,
    )

    # relationship backrefs:
    # - revisions (EditingRevision.editable)

    def __repr__(self):
        return format_repr(self, 'id', 'contribution_id', 'type')

    @locator_property
    def locator(self):
        return dict(self.contribution.locator, type=self.type.name)

    @property
    def event(self):
        return self.contribution.event

    @property
    def log_title(self):
        return f'"{self.contribution.title}" ({orig_string(self.type.title)})'

    @property
    def valid_revisions(self):
        return [r for r in self.revisions if not r.is_undone]

    @property
    def latest_revision(self):
        return self.valid_revisions[-1] if self.valid_revisions else None

    @property
    def latest_revision_with_files(self):
        from .revision_files import EditingRevisionFile
        from .revisions import EditingRevision
        return (EditingRevision.query
                .filter_by(editable=self, is_undone=False)
                .join(EditingRevisionFile)
                .order_by(EditingRevision.created_dt.desc())
                .first())

    @property
    def last_update_dt(self):
        return self.latest_revision.last_update_dt if self.latest_revision else None

    def _has_general_editor_permissions(self, user):
        """Whether the user has general editor permissions on the Editable.

        This means that the user has editor permissions for the editable's type,
        but does not need to be the assigned editor.
        """
        # Editing (and event) managers always have editor-like access
        return (
            self.event.can_manage(user, permission='editing_manager') or
            self.event.can_manage(user, permission=self.type.editor_permission)
        )

    def can_see_timeline(self, user):
        """Whether the user can see the editable's timeline.

        This is pure read access, without any ability to make changes
        or leave comments.
        """
        # Anyone with editor access to the editable's type can see the timeline.
        # Users associated with the editable's contribution can do so as well.
        return (
            self._has_general_editor_permissions(user) or
            self.contribution.can_submit_proceedings(user) or
            self.contribution.is_user_associated(user, check_abstract=True)
        )

    def can_perform_submitter_actions(self, user):
        """Whether the user can perform any submitter actions.

        These are actions such as uploading a new revision after having
        been asked to make changes or approving/rejecting changes made
        by an editor.
        """
        # If the user can't even see the timeline, we never allow any modifications
        if not self.can_see_timeline(user):
            return False
        # Anyone who can submit new proceedings can also perform submitter actions,
        # i.e. the abstract submitter and anyone with submission access to the contribution.
        return self.contribution.can_submit_proceedings(user)

    def can_perform_editor_actions(self, user):
        """Whether the user can perform any Editing actions.

        These are actions usually made by the assigned Editor of the
        editable, such as making changes, asking the user to make changes,
        or approving/rejecting the editable.
        """
        from indico.modules.events.editing.settings import editable_type_settings

        # If the user can't even see the timeline, we never allow any modifications
        if not self.can_see_timeline(user):
            return False
        # Editing/event managers can perform actions when they are the assigned editor
        # even when editing is disabled in the settings
        if self.editor == user and self.event.can_manage(user, permission='editing_manager'):
            return True
        # Editing needs to be enabled in the settings otherwise
        if not editable_type_settings[self.type].get(self.event, 'editing_enabled'):
            return False
        # Editors need the permission on the editable type and also be the assigned editor
        if self.editor == user and self.event.can_manage(user, permission=self.type.editor_permission):
            return True
        return False

    def can_use_internal_comments(self, user):
        """Whether the user can create/see internal comments."""
        return self._has_general_editor_permissions(user)

    def can_see_restricted_revisions(self, user):
        """Whether the user can see restricted revisions."""
        return self._has_general_editor_permissions(user)

    def can_see_editor_names(self, user, actor=None):
        """Whether the user can see the names of editing team members.

        This is always true if team anonymity is not enabled; otherwise only
        users who are member of the editing team will see names.

        If an `actor` is set, the check applies to whether the name of this
        particular user can be seen.
        """
        from indico.modules.events.editing.settings import editable_type_settings

        return (
            not editable_type_settings[self.type].get(self.event, 'anonymous_team') or
            (actor and not self.can_see_editor_names(actor)) or
            self._has_general_editor_permissions(user)
        )

    def can_comment(self, user):
        """Whether the user can comment on the editable."""
        # We allow any user associated with the contribution to comment, even if they are
        # not authorized to actually perform submitter actions.
        return (self.event.can_manage(user, permission=self.type.editor_permission)
                or self.event.can_manage(user, permission='editing_manager')
                or self.contribution.is_user_associated(user, check_abstract=True))

    def can_assign_self(self, user):
        """Whether the user can assign themselves on the editable."""
        from indico.modules.events.editing.settings import editable_type_settings
        type_settings = editable_type_settings[self.type]
        if self.editor and (self.editor == user or not self.can_unassign(user)):
            return False
        return ((self.event.can_manage(user, permission=self.type.editor_permission)
                 and type_settings.get(self.event, 'editing_enabled')
                 and type_settings.get(self.event, 'self_assign_allowed'))
                or self.event.can_manage(user, permission='editing_manager'))

    def can_unassign(self, user):
        """Whether the user can unassign the editor of the editable."""
        from indico.modules.events.editing.settings import editable_type_settings
        type_settings = editable_type_settings[self.type]
        return (self.event.can_manage(user, permission='editing_manager')
                or (self.editor == user
                    and self.event.can_manage(user, permission=self.type.editor_permission)
                    and type_settings.get(self.event, 'editing_enabled')
                    and type_settings.get(self.event, 'self_assign_allowed')))

    def can_delete(self, user):
        """Whether the user can delete the editable."""
        return self.event.can_manage(user)

    @property
    def review_conditions_valid(self):
        from indico.modules.events.editing.models.review_conditions import EditingReviewCondition
        query = EditingReviewCondition.query.with_parent(self.event).filter_by(type=self.type)
        review_conditions = [{ft.id for ft in cond.file_types} for cond in query]
        if not review_conditions:
            return True
        file_types = {file.file_type_id for file in self.latest_revision_with_files.files}
        return any(file_types >= cond for cond in review_conditions)

    @property
    def editing_enabled(self):
        from indico.modules.events.editing.settings import editable_type_settings
        return editable_type_settings[self.type].get(self.event, 'editing_enabled')

    @property
    def external_timeline_url(self):
        return url_for('event_editing.editable', self, _external=True)

    @property
    def timeline_url(self):
        return url_for('event_editing.editable', self)

    def log(self, *args, **kwargs):
        """Log with prefilled metadata for the editable."""
        return self.event.log(*args, meta={'editable_id': self.id}, **kwargs)


@listens_for(orm.mapper, 'after_configured', once=True)
def _mappers_configured():
    from .revision_files import EditingRevisionFile
    from .revisions import EditingRevision, RevisionType

    # Editable.state -- the state of the editable itself
    cases = db.cast(db.case({
        RevisionType.new: EditableState.new,
        RevisionType.ready_for_review: EditableState.ready_for_review,
        RevisionType.needs_submitter_confirmation: EditableState.needs_submitter_confirmation,
        RevisionType.changes_acceptance: EditableState.accepted_submitter,
        RevisionType.changes_rejection: EditableState.needs_submitter_changes,
        RevisionType.needs_submitter_changes: EditableState.needs_submitter_changes,
        RevisionType.acceptance: EditableState.accepted,
        RevisionType.rejection: EditableState.rejected,
        RevisionType.replacement: EditableState.ready_for_review,
        RevisionType.reset: EditableState.ready_for_review,
    }, value=EditingRevision.type), PyIntEnum(EditableState))
    query = (select([cases])
             .where((EditingRevision.editable_id == Editable.id) & ~EditingRevision.is_undone)
             .order_by(EditingRevision.created_dt.desc())
             .limit(1)
             .correlate_except(EditingRevision)
             .scalar_subquery())
    Editable.state = column_property(query)

    # Editable.revision_count -- the number of revisions with files the editable has
    query = (select([db.func.count(EditingRevision.id.distinct())])
             .where((EditingRevision.editable_id == Editable.id) & ~EditingRevision.is_undone)
             .join(EditingRevisionFile)
             .correlate_except(EditingRevision)
             .scalar_subquery())
    Editable.revision_count = column_property(query)
