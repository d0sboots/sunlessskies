#!/usr/bin/python3

"""Module for reading the Sunless Skies data files.

To use, this requires the following files:
* Backers.dat
* areas.dat
* bargains.dat
* events.dat
* exchanges.dat
* personas.dat
* prospects.dat
* qualities.dat
* settings.dat

All of these are extracted from the game file
"Sunless Skies_Data/resources.assets", using a tool like Unity Asset Bundle
Extractor. To help locate them, they all have the type "TextAsset", at the
time of this writing they start at Path ID: 1429, and events is the single
largest asset if you sort by size.

If some of the files are missing, a warning will be printed and parsing will
continue with the others. The most critical ones are events and qualities.
"""
# pylint: disable=too-few-public-methods

import cProfile
from contextlib import closing
import io
import struct

_DEBUG = False

class _Reader:
    """Reads binary data from a file stream"""
    __slots__ = ('buf_reader', 'read')

    def __init__(self, fname, /):
        self.buf_reader = io.BufferedReader(io.FileIO(fname))
        if not _DEBUG:
            self.read = self.buf_reader.read
        else:
            read_fun = self.buf_reader.read
            def print_wrapper(count):
                result = read_fun(count)
                print(f'Read {result!r}')
                return result
            self.read = print_wrapper
        # Check if the file has Unity header bits, and skip them if so.
        # Takes advantage of the fact that peek returns the whole buffer.
        start = self.buf_reader.peek()
        name_len = int.from_bytes(start[:4], 'little')
        if name_len < 20:  # If it is a reasonable size...
            padding = -name_len & 3
            blen = name_len + 4 + padding
            # If all the padding bytes are zero, and the name is entirely in
            # the upper/lowercase range, we can safely assume it's a Unity
            # header. That means skipping the name, name padding, plus 8 bytes
            # for the name length and the content length.
            if start[name_len+4:blen] == b'\0' * padding and all(
                0x40 < x <= 0x7A for x in start[4:name_len+4]):
                self.read(blen + 4)

    def close(self):
        """Close the reader"""
        self.buf_reader.close()

    def read_unpack(self, fmt, size, /):
        """Unpack a tuple using struct.unpack()"""
        return struct.unpack(fmt, self.read(size))[0]

    def read_varint(self):
        """Read a varint value from the stream"""
        shift = 0
        acc = 0
        while True:
            byte = self.read(1)[0]
            acc |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        return acc

    def read_bool(self):
        """Helper for reading a single bool"""
        return self.read(1)[0]

    def read_int32(self):
        """Helper for reading a single int32"""
        return int.from_bytes(self.read(4), 'little', signed=True)

    def read_optional_int32(self):
        """Read an optional int32, returning None if not present"""
        return self.read_int32() if self.read(1)[0] else None

    def read_optional_int64(self):
        """Read an optional int64, returning None if not present"""
        if not self.read(1)[0]:
            return None
        return int.from_bytes(self.read(8), 'little', signed=True)

    def read_base_string(self):
        """Read a base UTF-8 string"""
        slen = self.read_varint()
        if _DEBUG:
            print(f'String size: 0x{slen:X}')
        res = self.read(slen).decode()
        if _DEBUG:
            print('String: ' + res)
        return res

    def read_string(self):
        """Read an optional string, returning None if not present"""
        if not self.read(1)[0]:
            return None
        return self.read_base_string()

    def read_object(self, cls, /):
        """Read an optional object field, returning None if not present"""
        # There are two layers of optional: An outer one on the field and an
        # inner one on the object itself. It's essentially redundant, they
        # both mean the same thing.
        read_fun = self.read
        if read_fun(1)[0] and read_fun(1)[0]:
            return cls(self)
        return None

    def read_datetime(self):
        # pylint: disable=no-self-use
        """Specialty method that doesn't actually read anything"""
        return 0

    def read_optional_datetime(self):
        """Specialty method that (optionally) doesn't read anything"""
        return 0 if self.read(1)[0] else None

    def read_raw_array(self, cls, /):
        """Read an array of optional objects"""
        alen = self.read_int32()
        if _DEBUG:
            print(f'Array len: {alen} for {cls.__name__}')
        # Arrays only have the single inner level of optionality, so we can't
        # use read_object().
        return [cls(self) if self.read(1)[0] else None
                for x in range(alen)]

    def read_array(self, cls, /):
        """Read an optional array of optional objects, returning None if not present"""
        if not self.read(1)[0]:
            return None
        return self.read_raw_array(cls)


class Object:
    """Generic object base type that powers the rest of the type hierarchy.

    All subclasses of this are dumb struct types that contain no real logic;
    they simply describe their layout. This class sets up the code for
    each subclass by hooking __init_subclass__ so it can do parsing, __repr__,
    etc., without needing a full-blown metaclass.
    """

    _labels = 'id,name'

    def __init_subclass__(cls):
        # pylint: disable=exec-used,no-member
        """Does the thing"""
        layout = [x.strip().split(':', 1) for x in cls._layout.strip().split('\n')]
        for field in layout:
            # Append parens as needed, so that we get method calls later on.
            if not field[1][-1] == ')':
                field[1] += '()'
        cls.__slots__ = tuple(x[0] for x in layout)
        # We dynamically create this code, so that it will be compiled once
        # and then run at full speed.
        codestring = '    self.{0} = reader.read_{1}'
        if _DEBUG:
            codestring = ("    print(f'@{{reader.buf_reader.tell():X}} " +
                cls.__name__ + ".{0}')\n" + codestring)
        code = ['def __init__(self, reader):'] + [
            codestring.format(*x) for x in layout]
        localz = {}
        exec(compile('\n'.join(code), f'<dynamic {cls.__name__} code>', 'exec'),
                globals(), localz)
        __init__ = localz['__init__']
        __init__.__qualname__ = f'{cls.__name__}.__init__'
        cls.__init__ = __init__
        # Precompute replacement string for speed
        fmt = ', '.join(x + '={}' for x in cls.__slots__)
        cls._repr_format = f'{cls.__name__}({fmt})'

        cls._str_attrs = cls._labels.split(',')
        fmt = ', '.join(x + '={}' for x in cls._str_attrs)
        cls._str_format = f'{cls.__name__}({fmt})'

    def __repr__(self):
        """Print all the attributes of the class"""
        return self._repr_format.format(
                *[getattr(self, x) for x in self.__slots__])

    def __str__(self):
        """An abbreviated version of the class, only attrs in _labels"""
        return self._str_format.format(
                *[getattr(self, x) for x in self._str_attrs])


class Area(Object):
    """Abstract areas in the game"""

    _layout = """description:string
    image_name:string
    world:object(World)
    market_access_permitted:bool
    move_message:string
    hide_name:bool
    random_postcard:bool
    map_x:int32
    map_y:int32
    unlocks_with_quality:object(Quality)
    show_ops:bool
    premium_sub_required:bool
    name:string
    id:int32
    """


class AspectQPossession(Object):
    """Qualities possessed by other qualites"""

    _layout = """quality:object(Quality)
    xp:int32
    effective_level_modifier:int32
    target_quality:object(Quality)
    target_level:optional_int32
    completion_message:string
    level:int32
    associated_quality:object(Quality)
    id:int32
    """
    _labels = 'id,target_quality'


class Branch(Object):
    """Story event branch"""

    _layout = """success_event:object(Event)
    default_event:object(Event)
    rare_default_event:object(Event)
    rare_default_event_chance:int32
    rare_success_event:object(Event)
    rare_success_event_chance:int32
    parent_event:object(Event)
    qualities_required:array(BranchQRequirement)
    image:string
    description:string
    owner_name:string
    date_time_created:datetime
    currency_cost:int32
    archived:bool
    rename_quality_category:optional_int32
    button_text:string
    ordering:int32
    act:object(Stub)
    action_cost:int32
    name:string
    id:int32
    """


class BranchQRequirement(Object):
    """Branch requirements"""

    _layout = """difficulty_level:optional_int32
    difficulty_advanced:string
    visible_when_requirement_failed:bool
    custom_locked_message:string
    custom_unlocked_message:string
    is_cost_requirement:bool
    min_level:optional_int32
    max_level:optional_int32
    min_advanced:string
    max_advanced:string
    associated_quality:object(Quality)
    id:int32
    """
    _labels = 'id,min_level,max_level,associated_quality'


class Deck(Object):
    """Card deck (inherited from Fallen London)"""

    _layout = """world:object(World)
    name:string
    image_name:string
    ordering:int32
    description:string
    availability:int32
    draw_size:int32
    max_cards:int32
    id:int32
    """


class Event(Object):
    """Events (base of all actions that happen)"""

    _layout = """child_branches:array(Branch)
    parent_branch:object(Branch)
    qualities_affected:array(EventQEffect)
    qualities_required:array(EventQRequirement)
    image:string
    second_image:string
    description:string
    tag:string
    exotic_effects:string
    note:string
    challenge_level:int32
    uncleared_edit_at:optional_datetime
    last_edited_by:object(User)
    ordering:unpack('f',4)
    show_as_message:bool
    living_story:object(Stub)
    link_to_event:object(Event)
    deck:object(Deck)
    category:int32
    limited_to_area:object(Area)
    world:object(World)
    transient:bool
    stickiness:int32
    move_to_area_id:int32
    move_to_area:object(Area)
    move_to_domicile:object(Stub)
    switch_to_setting:object(Setting)
    fate_points_change:int32
    booty_value:int32
    log_in_journal_against_quality:object(Quality)
    setting:object(Setting)
    urgency:int32
    teaser:string
    owner_name:string
    date_time_created:datetime
    distribution:int32
    autofire:bool
    can_go_back:bool
    name:string
    id:int32
    """


class EventQEffect(Object):
    """Result of an event branch"""

    _layout = """priority:optional_int32
    force_equip:bool
    only_if_no_more_than_advanced:string
    only_if_at_least:optional_int32
    only_if_no_more_than:optional_int32
    set_to_exactly_advanced:string
    change_by_advanced:string
    only_if_at_least_advanced:string
    set_to_exactly:optional_int32
    target_quality:object(Quality)
    target_level:optional_int32
    completion_message:string
    level:int32
    associated_quality:object(Quality)
    id:int32
    """
    _labels = 'id,associated_quality'


class EventQRequirement(Object):
    """Requirements for an entire event (as opposed to just a branch)"""

    _layout = """min_level:optional_int32
    max_level:optional_int32
    min_advanced:string
    max_advanced:string
    associated_quality:object(Quality)
    id:int32
    """
    _labels = 'id,min_level,max_level,associated_quality'


class Exchange(Object):
    """Stores"""

    _layout = """id:int32"""


class Stub(Object):
    """Never actually deserialized, but exists in the hierarchy"""

    _layout = """id:int32"""


class QEnhancement(Object):
    """Buffs associated with Qualities"""

    _layout = """level:int32
    associated_quality:object(Quality)
    id:int32
    """
    _labels = 'id,level,associated_quality'

# public enum QualityAllowedOn
# {
#     Unspecified,
#     Character,
#     QualityAndCharacter,
#     Event,
#     Branch,
#     Persona,
#     User
# }

# public enum DifficultyTestType
# {
#     Broad,
#     Narrow
# }

# public enum Nature
# {
#     Unspecified,
#     Status,
#     Thing
# }

# public enum Category
# {
#     Academic = 16000,
#     Accomplishment = 5050,
#     Acquaintance = 5025,
#     Advantage = 160,
#     Affiliation = 13000,
#     Ambition = 7000,
#     Avatar = 39000,
#     BasicAbility = 1000,
#     Boots = 105,
#     Cartography = 17000,
#     Circumstance = 37000,
#     Clothing = 107,
#     Club = 12000,
#     Companion = 106,
#     ConstantCompanion = 11000,
#     Contacts = 6000,
#     Contraband = 18000,
#     Curiosity = 150,
#     Currency = 1,
#     Destiny = 60000,
#     Document = 170,
#     Dreams = 5002,
#     Elder = 19000,
#     Gloves = 104,
#     Goods = 200,
#     GreatGame = 70001,
#     Hat = 103,
#     HomeComfort = 15000,
#     Infernal = 20000,
#     Influence = 21000,
#     Intrigue = 5001,
#     Key = 45000,
#     Knowledge = 50000,
#     Legal = 29000,
#     Literature = 22000,
#     Lodgings = 22500,
#     Luminosity = 23000,
#     MajorLateral = 34000,
#     Menace = 5500,
#     MinorLateral = 36000,
#     Modfier = 70000,
#     Mysteries = 24000,
#     Nostalgia = 25000,
#     Objective = 40000,
#     Profession = 3000,
#     Progress = 5200,
#     Quest = 35000,
#     Quirk = 5004,
#     RagTrade = 26000,
#     Ratness = 27000,
#     Reputation = 5003,
#     Route = 8000,
#     Rubbery = 32000,
#     Rumour = 28000,
#     Sustenance = 70003,
#     Seasonal = 9000,
#     Ship = 10000,
#     SidebarAbility = 33000,
#     SpecificAbility = 2000,
#     Story = 5000,
#     Timer = 13999,
#     Transportation = 14000,
#     Unspecified = 0,
#     Venture = 5100,
#     Weapon = 101,
#     WildWords = 30000,
#     Wines = 31000,
#     Hidden = 6661,
#     Randomizer = 6662,
#     ZeeTreasures = 70002,
#     Bridge = 70004,
#     Plating = 70005,
#     Auxiliary = 70006,
#     SmallWeapon = 70007,
#     LargeWeapon = 70008,
#     Scout = 70009
# }

class Quality(Object):
    """Qualities, i.e. stuff and progression"""

    _layout = """qualities_possessed:array(AspectQPossession)
    relationship_capable:bool
    plural_name:string
    owner_name:string
    description:string
    image:string
    notes:string
    tag:string
    cap:optional_int32
    cap_advanced:string
    himble_level:int32
    use_pyramid_numbers:bool
    pyramid_number_increase_limit:int32
    available_at:string
    prevent_naming:bool
    css_classes:string
    qeffect_priority:int32
    qeffect_minimal_limit:optional_int32
    world:object(World)
    ordering:int32
    is_slot:bool
    limited_to_area:object(Area)
    assign_to_slot:object(Quality)
    parent_quality:object(Quality)
    persistent:bool
    visible:bool
    enhancements:array(QEnhancement)
    enhancements_description:string
    second_chance_quality:object(Quality)
    use_event:object(Event)
    difficulty_test_type:int32
    difficulty_scaler:int32
    allowed_on:int32
    nature:int32
    category:int32
    level_description_text:string
    change_description_text:string
    descending_change_description_text:string
    level_image_text:string
    variable_description_text:string
    name:string
    id:int32
    """


class Setting(Object):
    """???"""

    _layout = """world:object(World)
    owner_name:string
    personae:array(Stub)
    starting_area:object(Area)
    starting_domicile:object(Stub)
    items_usable_here:bool
    exchange:object(Exchange)
    turn_length_seconds:int32
    max_actions_allowed:int32
    max_cards_allowed:int32
    actions_in_period_before_exhaustion:int32
    description:string
    name:string
    id:int32
    """


class User(Object):
    """A bunch of stuff that was mostly inherited from Fallen London?"""

    _layout = """qualities_possessed:array(UserQPossession)
    name:string
    started_in_world:object(World)
    email_address:string
    facebook_email:string
    password_hash:string
    confirmation_code:string
    twitter_id:optional_int64()
    facebook_id:optional_int64()
    google_id:string
    google_auth_token:string
    google_auth_token_secret:string
    google_email:string
    twitter_auth_token:string
    twitter_auth_token_secret:string
    facebook_auth_token:string
    facebook_auth_token_secret:string
    source:string
    entered_via_content_id:int32
    entered_via_character_id:int32
    status:int32
    email_verified:bool
    echo_via_network:int32
    message_via_network:int32
    message_about_nastiness:bool
    message_about_niceness:bool
    message_about_announcements:bool
    story_event_message:bool
    default_privilege_level:int32
    logged_in_via:int32
    is_broadcast_target:bool
    mystery_prize_tracking:int32
    recruited:int32
    temp_id:string
    created_at:datetime
    last_logged_in_at:optional_datetime
    last_active_at:optional_datetime
    ip:string
    last_access_code:string
    world_privileges:array(UserWorldPrivilege)
    sr_purchased_nex_in_lifetime:int32
    fate_points_gained_through_game_in_lifetime:int32
    nex:int32
    id:int32
    """


class UserQPossession(Object):
    """Qualities that a user has?"""

    _layout = """xp:int32
    effective_level_modifier:int32
    target_quality:object(Quality)
    target_level:optional_int32
    completion_message:string
    level:int32
    associated_quality:object(Quality)
    id:int32
    """
    _labels = 'id,level,associated_quality'


class UserWorldPrivilege(Object):
    """???"""

    _layout = """world:object(World)
    privilege_level:int32
    user:object(User)
    id:int32
    """
    _labels = 'id,user'


class World(Object):
    """A lot of general stuff"""

    _layout = """general_quality_catalogue:bool
    show_card_titles:bool
    character_creation_page_text:string
    end_page_text:string
    front_page_text:string
    custom_css:string
    credits:string
    description:string
    name:string
    domain:string
    promoted:int32
    default_setting:object(Setting)
    facebook_auth:bool
    twitter_auth:bool
    email_auth:bool
    facebook_aPIKey:string
    facebook_app_id:string
    facebook_app_secret:string
    game_user_twitter_auth_token:string
    game_user_twitter_auth_token_secret:string
    twitter_consumer_key:string
    twitter_consumer_secret:string
    twitter_callback_url:string
    amazon_hosted_image_url:string
    amazon_bucket_name:string
    style_sheet:string
    logo_image:string
    default_starting_setting:object(Setting)
    owner:object(User)
    is_portal_world:bool
    monetizes:bool
    payment_email_address:string
    support_email_address:string
    system_from_email_address:string
    last_updated:datetime
    update_notes:string
    publish_state:int32
    genre:int32
    id:int32
    """

with cProfile.Profile() as pr:
    with closing(_Reader('events.dat')) as reader:
        for elem in reader.read_raw_array(Event):
            print(elem)
    pr.print_stats()
