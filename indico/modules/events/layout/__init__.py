# This file is part of Indico.
# Copyright (C) 2002 - 2025 CERN
#
# Indico is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see the
# LICENSE file for more details.

from flask import session
from jinja2.filters import do_filesizeformat

from indico.core import signals
from indico.core.logger import Logger
from indico.core.settings.converters import EnumConverter
from indico.modules.events.features.base import EventFeature
from indico.modules.events.layout.models.principals import MenuEntryPrincipal
from indico.modules.events.models.events import EventType
from indico.modules.events.settings import EventSettingsProxy, ThemeSettingsProxy
from indico.modules.logs import EventLogRealm, LogKind
from indico.modules.users import NameFormat
from indico.util.i18n import _
from indico.web.flask.util import url_for
from indico.web.menu import SideMenuItem


EVENT_BANNER_WIDTH = 950
EVENT_LOGO_WIDTH = 200

# Theme settings that can be overridden via theme user settings. This works bidirectionally,
# ie if a theme's settings has all the keys set to True, then the user setting will default
# to True as well.
OVERRIDABLE_THEME_SETTINGS = {
    'inline_minutes': {'show_notes'},
    'numbered_contributions': {'hide_duration', 'hide_session_block_time', 'hide_end_time', 'number_contributions'}
}

logger = Logger.get('events.layout')
layout_settings = EventSettingsProxy('layout', {
    'is_searchable': True,
    'show_nav_bar': True,
    'show_social_badges': True,
    'name_format': None,
    'show_banner': False,
    'header_text_color': '',
    'header_logo_as_banner': True,
    'header_background_color': '',
    'announcement': None,
    'show_announcement': False,
    'use_custom_css': False,
    'theme': None,
    'timetable_theme': None,
    'timetable_theme_settings': {},
    'use_custom_menu': False,
    'timetable_by_room': False,
    'timetable_detailed': False,
    'show_vc_rooms': False,
}, converters={
    'name_format': EnumConverter(NameFormat)
})

theme_settings = ThemeSettingsProxy()


def get_theme_global_settings(event, theme):
    """Get the global settings for a theme.

    Some global theme settings such as 'show_notes' may be overridden by the
    event-specific user settings ('user_settings' in themes.yaml).
    These are saved in the event's layout settings under timetable_theme_settings.
    """
    settings = theme_settings.themes[theme].get('settings', {})
    # Ignore user settings when the selected theme does not match the event's theme
    if event.theme != theme:
        return settings

    # Override global settings with user settings, if present
    settings = settings.copy()
    event_user_settings = layout_settings.get(event, 'timetable_theme_settings')
    for user_key, theme_keys in OVERRIDABLE_THEME_SETTINGS.items():
        if user_key not in event_user_settings:
            continue
        settings.update(dict.fromkeys(theme_keys, event_user_settings[user_key]))
    return settings


@signals.event.created.connect
def _event_created(event, **kwargs):
    defaults = event.category.default_event_themes if event.category else None
    if not layout_settings.get(event, 'timetable_theme') and defaults and event.type_.name in defaults:
        layout_settings.set(event, 'timetable_theme', defaults[event.type_.name])


@signals.event.type_changed.connect
def _event_type_changed(event, **kwargs):
    theme = event.category.default_event_themes.get(event.type_.name) if event.category else None
    if theme is None:
        layout_settings.delete(event, 'timetable_theme')
    else:
        layout_settings.set(event, 'timetable_theme', theme)


@signals.menu.items.connect_via('event-management-sidemenu')
def _extend_event_management_menu_layout(sender, event, **kwargs):
    if not event.can_manage(session.user):
        return
    yield SideMenuItem('layout', _('Layout'), url_for('event_layout.index', event), section='customization')
    if event.type_ == EventType.conference:
        yield SideMenuItem('menu', _('Menu'), url_for('event_layout.menu', event), section='customization')
    if event.has_feature('images'):
        yield SideMenuItem('images', _('Images'), url_for('event_layout.images', event), section='customization')


@signals.event.cloned.connect
def _event_cloned(old_event, new_event, **kwargs):
    if old_event.type_ == EventType.conference:
        return
    # for meetings/lecture we want to keep the default timetable style in all cases
    theme = layout_settings.get(old_event, 'timetable_theme')
    if theme is not None:
        layout_settings.set(new_event, 'timetable_theme', theme)


@signals.event_management.get_cloners.connect
def _get_cloners(sender, **kwargs):
    from indico.modules.events.layout.clone import ImageCloner, LayoutCloner
    yield ImageCloner
    yield LayoutCloner


@signals.event.get_feature_definitions.connect
def _get_feature_definitions(sender, **kwargs):
    return ImagesFeature


@signals.event_management.image_created.connect
def _log_image_created(image, user, **kwargs):
    image.event.log(EventLogRealm.management, LogKind.positive, 'Layout',
                    f'Added image "{image.filename}"', user, data={
                        'File name': image.filename,
                        'File type': image.content_type,
                        'File size': do_filesizeformat(image.size)
                    })


@signals.event_management.image_deleted.connect
def _log_image_deleted(image, user, **kwargs):
    image.event.log(EventLogRealm.management, LogKind.negative, 'Layout',
                    f'Deleted image "{image.filename}"', user, data={
                        'File name': image.filename
                    })


@signals.users.merged.connect
def _merge_users(target, source, **kwargs):
    MenuEntryPrincipal.merge_users(target, source, 'menu_entry')


class ImagesFeature(EventFeature):
    name = 'images'
    friendly_name = _('Image manager')
    description = _('Allows event managers to attach images to the event, which can then be used from HTML code. '
                    'Very useful for e.g. sponsor logos and conference custom pages.')

    @classmethod
    def is_default_for_event(cls, event):
        return event.type_ == EventType.conference
