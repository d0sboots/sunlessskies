#!/usr/bin/python3

"""Utility for editing the Sunless Skies wiki.

This command-line script (usually) produces output on stdout in a format that
can be directly cut-and-pasted to the edit box of pages at
https://sunlessskies.gamepedia.com/. In the usual case where there is existing
content, replace that content entirely, and then use the diff feature to add
back in flavor text that was overwritten.

To run, this requires the following files in the current directory:
* areas.dat
* backers.dat
* bargains.dat
* events.dat
* exchanges.dat
* personas.dat
* prospects.dat
* qualities.dat
* settings.dat

These must be extracted from the game files. See the module help in
"sunless.py" for details.
"""

import argparse
import enum
import re
import sys

import sunless

AREAS_MAP = {}

def init_globals(data):
    """Initialize all the global data needed by other functions."""
    for item in data.areas:
        AREAS_MAP[item.id] = item

def pascal_case(value):
    """Convert strings or enums to PascalCase"""
    if isinstance(value, enum.Enum):
        value = value.name
    return value.title().replace('_', '')

# Matches HTML tags like '<i>' or '</i>'
_SANITIZE_PAT = re.compile('<[^>]*>')

def sanitize(name):
    """Strip HTML tags that are problematic in names"""
    return _SANITIZE_PAT.sub('', name)

def fuzzy_lookup_item(name_or_id, lst):
    """Lookup an item by either name or id.

    Looking up by id is exact match. Looking up by name is by containment, and
    if the term is entirely lowercase then it's also case-insensitive.
    Multiple matches will throw an exception, unless one of them was an exact
    match.
    """
    try:
        idd = int(name_or_id)
        for val in lst:
            if val.id == idd:
                return val
        raise RuntimeError('Id %d not found!' % idd)
    except ValueError:
        insensitive = name_or_id.islower()
        matches = []
        for val in lst:
            name = val.name or ''
            if name_or_id == name:
                return val
            if insensitive:
                name = name.lower()
            if name_or_id in name:
                matches.append(val)
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise RuntimeError(f'No name containing {name_or_id!r} found!') from None
        raise RuntimeError(
            f'Multiple matches for {name_or_id!r}: {[x.name for x in matches]}') from None

def dump_raw_qualities(data, /, sort=False):
    """Print the table of raw qualities"""
    qualities = data.qualities
    if sort:  # Don't modify actual collection
        qualities = sorted(qualities, key=lambda x: x.id)
    for item in qualities:
        print('* {}: [[{}]] ({}, {})'.format(item.id, sanitize(item.name),
            pascal_case(item.nature), pascal_case(item.category)))

def dump_raw_events(data, /, sort=False):
    """Print the table of raw events"""
    events = data.events
    if sort:  # Don't modify actual collection
        events = sorted(events, key=lambda x: x.id)
    for item in events:
        fmt = '* {}: [[{}]] {}|{}'
        area = ''
        if item.limited_to_area:
            area = '({}) '.format(
                sanitize(AREAS_MAP[item.limited_to_area.id].name))
        image = ''
        if item.image:
            image = f' [[:File:{item.image}.png]]'
        print(fmt.format(item.id, sanitize(item.name), area, image))


# pylint: disable=too-many-branches
def main():
    """Main function, keeps a separate scope"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--dump_event',
                        help='Lookup a specific event, by name or id')
    parser.add_argument('--dump_quality',
                        help='Lookup a specific quality, by name or id')
    parser.add_argument('--dump_area',
                        help='Lookup a specific area, by name or id')
    parser.add_argument('--dump_shop',
                        help='Lookup a specific shop, by name or id')
    parser.add_argument('--quality',
                        help='Output wiki text for a quality, looked up by name or id')
    parser.add_argument('--shop',
                        help='Output wiki text for a shop, looked up by name or id')
    parser.add_argument('--raw_events', action='store_true',
                        help='Output wiki text for a raw dump of all events'
                        '(https://sunlessskies.gamepedia.com/Raw_Dump_(Events))')
    parser.add_argument('--raw_qualities', action='store_true',
                        help='Output wiki text for a raw dump of all qualities'
                        '(https://sunlessskies.gamepedia.com/Raw_Dump_(Qualities))')
    parser.add_argument('--raw_shops', action='store_true',
                        help='Output a raw dump of all shops (Not in wiki format)')
    parser.add_argument('--sort', action='store_true',
                        help="""Sort the raw dump by id, instead of listing in
                        serialized order""")
    parser.add_argument('--shops_page', action='store_true',
                        help='Output wiki text for the Shops page '
                        '(https://sunlessskies.gamepedia.com/Shops)')
    parser.add_argument('--slice', action='store_true',
                        help='Pretty-print *something*, sliced by various fields.')
    args = parser.parse_args()

    print('Reading data... ', end='', flush=True, file=sys.stderr)
    data = sunless.load_all()
    init_globals(data)
    print('Done!', flush=True, file=sys.stderr)

    try:
        item = None
        if args.dump_event:
            item = fuzzy_lookup_item(args.dump_event, data.events)
        if args.dump_quality:
            item = fuzzy_lookup_item(args.dump_quality, data.qualities)
        if args.dump_area:
            item = fuzzy_lookup_item(args.dump_area, data.areas)
        if args.dump_shop:
            item = fuzzy_lookup_item(args.dump_shop, MakeShopList())[PARENT_GROUP]
            for shop in item[SHOPS]:
                del shop[PARENT_GROUP]
        if item:
            print(item)
        else:
            if args.shop:
                WikiShop(fuzzy_lookup_item(args.shop, MakeShopList()))
            elif args.quality:
                WikiQuality(fuzzy_lookup_item(args.quality, data.qualities))
            elif args.slice:
                PrintBySlice(data.qualities, QualitySlice1)
            elif args.raw_qualities:
                dump_raw_qualities(data, args.sort)
            elif args.raw_events:
                dump_raw_events(data, args.sort)
            elif args.raw_shops:
                DumpRawShops()
            elif args.shops_page:
                ShopsPage()
            else:
                print('Nothing to do!', file=sys.stderr)
    except RuntimeError as ex:
        print(ex, file=sys.stderr)

if __name__ == '__main__':
    main()
