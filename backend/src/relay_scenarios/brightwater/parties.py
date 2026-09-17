"""Brightwater customers and vendors (fictional)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final

from relay.canonical.enums import PartyType, PaymentMethod
from relay.canonical.records import Party
from relay.core.currency import Currency
from relay_scenarios.brightwater import constants as k
from relay_scenarios.errors import ScenarioConsistencyError
from relay_scenarios.rng import ScenarioRng

USD: Final = Currency.of("USD")
EUR: Final = Currency.of("EUR")


class Segment(StrEnum):
    GROCER = "grocer"
    RESTAURANT = "restaurant"
    EXPORT = "export"
    DORMANT = "dormant"  # active, no H1 activity
    HISTORICAL = "historical"  # inactive, no H1 activity


class Warehouse(StrEnum):
    PORTLAND = "PDX"
    SEATTLE = "SEA"
    BOISE = "BOI"


@dataclass(frozen=True, slots=True)
class CustomerProfile:
    party: Party
    segment: Segment
    warehouse: Warehouse
    receipt_method: PaymentMethod


class VendorCategory(StrEnum):
    PRODUCER = "producer"
    PACKAGING = "packaging"
    FREIGHT = "freight"
    UTILITY = "utility"
    LANDLORD = "landlord"
    FUEL = "fuel"
    MAINTENANCE = "maintenance"
    INSURANCE = "insurance"
    PROFESSIONAL = "professional"
    LEASE = "lease"
    SERVICES = "services"


@dataclass(frozen=True, slots=True)
class VendorProfile:
    party: Party
    category: VendorCategory
    expense_account: str
    payment_method: PaymentMethod
    created_by: str
    min_amount: Decimal
    max_amount: Decimal
    bills_per_half_year: int


_OR_CITIES: Final = (
    ("Portland", "OR", "972"),
    ("Beaverton", "OR", "970"),
    ("Hillsboro", "OR", "971"),
    ("Lake Oswego", "OR", "970"),
    ("Gresham", "OR", "970"),
    ("Salem", "OR", "973"),
    ("Eugene", "OR", "974"),
    ("Corvallis", "OR", "973"),
    ("Hood River", "OR", "970"),
)
_WA_CITIES: Final = (
    ("Seattle", "WA", "981"),
    ("Tacoma", "WA", "984"),
    ("Bellevue", "WA", "980"),
    ("Olympia", "WA", "985"),
    ("Everett", "WA", "982"),
    ("Vancouver", "WA", "986"),
)
_ID_CITIES: Final = (
    ("Boise", "ID", "837"),
    ("Meridian", "ID", "836"),
    ("Nampa", "ID", "836"),
    ("Idaho Falls", "ID", "834"),
)
_STREETS: Final = (
    "SE Division St",
    "NE Alberta St",
    "SW Barbur Blvd",
    "N Mississippi Ave",
    "NW 23rd Ave",
    "SE Belmont St",
    "Commercial St NE",
    "Pearl St",
    "Olive Way",
    "Rainier Ave S",
    "Pacific Ave",
    "Capitol Blvd",
    "W Idaho St",
    "E Fairview Ave",
    "Main St",
    "Broadway",
    "Oak St",
    "Center St",
    "Industrial Way",
    "Riverside Dr",
    "Market St",
    "Front Ave",
    "Harbor Dr",
    "Evergreen Pkwy",
)

_GROCERS: Final = (
    "Alder Street Market",
    "Belmont Natural Foods",
    "Cascade Harvest Grocers",
    "Driftwood Pantry",
    "Elk Rock Provisions",
    "Filbert & Oak Market",
    "Gorge Valley Co-op",
    "Hawthorne Fresh Market",
    "Ironwood Grocery",
    "Juniper Hill Foods",
    "Kestrel Market Hall",
    "Larch Mountain Mercantile",
    "Madrona Food Co-op",
    "Nehalem Bay Grocers",
    "Olallie Market",
    "Pioneer Square Provisions",
    "Quinault Country Store",
    "Riverbend Natural Grocers",
    "Salmonberry Market",
    "Tillamook Road Grocery",
    "Umpqua Valley Foods",
    "Vashon Island Market",
    "Whidbey Harvest Co-op",
    "Yakima Orchard Market",
    "Zigzag Mountain Grocery",
    "Bridgetown Pantry",
    "Coldwater Creek Market",
    "Deschutes Food Hall",
    "Ember Lane Grocers",
    "Foxglove Market",
    "Palouse Provisions",
    "Owyhee Mercantile",
    "Sawtooth Natural Foods",
    "Treasure Valley Market",
)

_RESTAURANT_WORDS: Final = (
    "Aster",
    "Birchwood",
    "Cobalt",
    "Dovetail",
    "Ember",
    "Fernwood",
    "Gristmill",
    "Harbor",
    "Indigo",
    "Jasper",
    "Kinfolk",
    "Larkspur",
    "Marrow",
    "Nettle",
    "Oxbow",
    "Pinewood",
    "Quarry",
    "Rookery",
    "Saffron",
    "Thimbleberry",
    "Umber",
    "Verbena",
    "Wildwood",
    "Yarrow",
    "Zephyr",
    "Anchor",
    "Bramble",
    "Copperleaf",
    "Dune",
    "Estuary",
    "Fable",
    "Greenhouse",
    "Heron",
    "Iris",
    "Juniper",
    "Kelp",
    "Lantern",
    "Magpie",
    "Northstar",
    "Orchard",
    "Parsnip",
    "Quince",
    "Redtail",
    "Sorrel",
    "Tamarack",
    "Upland",
    "Vine",
    "Willet",
    "Yellowjacket",
    "Alpine",
    "Basalt",
    "Chanterelle",
    "Driftless",
    "Elderberry",
    "Foundry",
    "Granary",
    "Hollow",
    "Ironclad",
    "Jubilee",
    "Keel",
    "Lumen",
    "Meadowlark",
    "Nimbus",
    "Oyster",
    "Paddle",
    "Quill",
    "Rivet",
    "Sparrow",
    "Tidewater",
    "Undertow",
    "Vesper",
    "Wren",
    "Yeoman",
    "Alder",
    "Bluebird",
    "Cinder",
    "Dogwood",
    "Eastside",
    "Fiddlehead",
    "Gull",
    "Huckleberry",
    "Inkwell",
    "Jetty",
    "Kiln",
    "Loam",
    "Millrace",
    "Nectar",
    "Otter",
    "Pumice",
    "Riverstone",
    "Salt Marsh",
    "Trillium",
    "Uproot",
    "Velvet",
    "Waxwing",
    "Yew",
    "Acorn",
    "Bellwether",
    "Canopy",
    "Drumlin",
    "Eddy",
    "Flint",
    "Gable",
    "Hearth",
    "Isle",
    "Jackdaw",
    "Kettle",
    "Lodestar",
    "Mossy Rock",
    "Nook",
    "Obsidian",
    "Plover",
    "Quarterdeck",
    "Ramble",
    "Sextant",
    "Thistle",
    "Ursa",
    "Vale",
    "Wharf",
    "Yardarm",
    "Arbor",
    "Bittern",
    "Cairn",
    "Delta",
    "Elm",
    "Firefly",
)
_RESTAURANT_TYPES: Final = (
    "Kitchen",
    "Bistro",
    "Cafe",
    "Taproom",
    "Eatery",
    "Grill",
    "Supper Club",
    "Tavern",
    "Deli",
    "Bakery",
    "Pizzeria",
    "Noodle House",
    "Brasserie",
    "Cantina",
    "Smokehouse",
)
_HISTORICAL_TYPES: Final = (
    "Market",
    "Cafe",
    "Catering",
    "Deli",
    "Foods",
    "Bistro",
    "Provisions",
    "Kitchen",
    "Grocery",
)
_HISTORICAL_WORDS_A: Final = (
    "Old",
    "Blue",
    "Red",
    "Green",
    "Silver",
    "Golden",
    "North",
    "South",
    "East",
    "West",
    "Little",
    "Big",
    "High",
    "Low",
    "Grand",
    "Twin",
    "Lone",
    "Hidden",
    "Sunny",
    "Misty",
)
_HISTORICAL_WORDS_B: Final = (
    "Pine",
    "Creek",
    "Ridge",
    "Mill",
    "Harbor",
    "Meadow",
    "Canyon",
    "Lake",
    "River",
    "Brook",
    "Hill",
    "Grove",
    "Field",
    "Stone",
    "Bridge",
    "Spring",
    "Butte",
    "Prairie",
    "Summit",
    "Hollow",
)

_PRODUCERS: Final = (
    "Willamette Valley Creamery",
    "Columbia Gorge Orchards",
    "Chinook Smokehouse Co.",
    "Blue Heron Preserves",
    "Mt. Hood Berry Farm",
    "Puget Sound Shellfish Co.",
    "Skagit Valley Grains",
    "Hells Canyon Honey",
    "Oregon Coast Seafood Traders",
    "Walla Walla Onion Growers",
    "Snake River Trout Farms",
    "Rogue Valley Cheese Works",
    "Tualatin Hazelnut Co.",
    "Klamath Basin Potato Co.",
    "Yamhill Charcuterie",
    "Olympic Peninsula Mushrooms",
    "Payette Valley Beef",
    "Siuslaw Cranberry Growers",
    "Bitterroot Bakehouse Supply",
    "Methow Valley Apples",
    "Coquille Dairy Cooperative",
    "Nisqually Salmon Co.",
    "Silvies River Lamb",
    "Wallowa Grass-Fed Beef",
    "Hood Canal Oyster Co.",
    "Kittitas Hay & Grain",
    "Umatilla Specialty Produce",
    "Cowlitz Creek Farms",
    "Grande Ronde Poultry",
    "Pend Oreille Wild Rice",
    "McKenzie River Mills",
    "Santiam Canning Co.",
    "Nooksack Berry Growers",
    "Clearwater Creamery",
    "Chehalis Valley Eggs",
    "Deschutes Brewing Supply Co-op",
    "Umpqua Oat Mill",
    "Wenatchee Pear Packers",
    "Malheur Onion Co.",
    "Palouse Lentil Growers",
    "Lummi Bay Seafood",
    "Hermiston Melon Farms",
    "Teton Valley Trout",
    "Yakima Hop & Herb",
    "Coos Bay Crab Co.",
    "Scappoose Organic Farms",
    "Boardman Tree Fruit",
    "Newberg Nut Growers",
)

_OTHER_VENDORS: Final = (
    # (name, category, expense account, method, min, max, bills per half-year)
    (
        "Pacific Coast Packaging LLC",
        VendorCategory.PACKAGING,
        "5150",
        PaymentMethod.ACH,
        "2400.00",
        "9800.00",
        26,
    ),
    (
        "Evergreen Box & Film",
        VendorCategory.PACKAGING,
        "5150",
        PaymentMethod.ACH,
        "900.00",
        "4200.00",
        12,
    ),
    (
        "Cascade Coldchain Logistics",
        VendorCategory.FREIGHT,
        "6400",
        PaymentMethod.CHECK,
        "1100.00",
        "5200.00",
        24,
    ),
    (
        "Northwest Reefer Transport",
        VendorCategory.FREIGHT,
        "6400",
        PaymentMethod.ACH,
        "900.00",
        "4800.00",
        24,
    ),
    (
        "Columbia River Freightways",
        VendorCategory.FREIGHT,
        "6400",
        PaymentMethod.ACH,
        "750.00",
        "4100.00",
        24,
    ),
    (
        "Blue Mountain Carriers",
        VendorCategory.FREIGHT,
        "6400",
        PaymentMethod.CHECK,
        "600.00",
        "3900.00",
        22,
    ),
    (
        "Treasure Valley Trucking",
        VendorCategory.FREIGHT,
        "6400",
        PaymentMethod.ACH,
        "650.00",
        "3600.00",
        22,
    ),
    (
        "Sound Cartage Co.",
        VendorCategory.FREIGHT,
        "6400",
        PaymentMethod.ACH,
        "500.00",
        "2900.00",
        20,
    ),
    (
        "Ridgeline Express",
        VendorCategory.FREIGHT,
        "6400",
        PaymentMethod.ACH,
        "450.00",
        "2600.00",
        20,
    ),
    (
        "Portland General Utilities",
        VendorCategory.UTILITY,
        "6200",
        PaymentMethod.ACH,
        "1080.00",
        "1420.00",
        6,
    ),
    (
        "Columbia Basin Water District",
        VendorCategory.UTILITY,
        "6210",
        PaymentMethod.ACH,
        "380.00",
        "610.00",
        6,
    ),
    (
        "Ridgewire Telecom",
        VendorCategory.UTILITY,
        "6220",
        PaymentMethod.ACH,
        "1240.00",
        "1390.00",
        6,
    ),
    (
        "Lombard Street Properties LLC",
        VendorCategory.LANDLORD,
        "6300",
        PaymentMethod.ACH,
        "8500.00",
        "8500.00",
        6,
    ),
    (
        "Duwamish Industrial Partners",
        VendorCategory.LANDLORD,
        "6310",
        PaymentMethod.ACH,
        "6420.00",
        "6420.00",
        6,
    ),
    (
        "Gowen Field Commerce Park",
        VendorCategory.LANDLORD,
        "6320",
        PaymentMethod.ACH,
        "4875.00",
        "4875.00",
        6,
    ),
    (
        "Pacific Fleet Fuel",
        VendorCategory.FUEL,
        "6420",
        PaymentMethod.ACH,
        "1800.00",
        "4600.00",
        26,
    ),
    (
        "Summit Refrigeration Services",
        VendorCategory.MAINTENANCE,
        "6600",
        PaymentMethod.CHECK,
        "640.00",
        "7800.00",
        5,
    ),
    (
        "Evergreen Mutual Insurance",
        VendorCategory.INSURANCE,
        "6510",
        PaymentMethod.CHECK,
        "5200.00",
        "8900.00",
        2,
    ),
    (
        "Hollis & Ward CPAs",
        VendorCategory.PROFESSIONAL,
        "6940",
        PaymentMethod.CHECK,
        "2800.00",
        "14500.00",
        3,
    ),
    (
        "Marlowe Ostrander LLP",
        VendorCategory.PROFESSIONAL,
        "6950",
        PaymentMethod.CHECK,
        "1500.00",
        "6200.00",
        2,
    ),
    (
        "Beaverton Forklift Leasing",
        VendorCategory.LEASE,
        "6610",
        PaymentMethod.ACH,
        "2140.00",
        "2360.00",
        6,
    ),
    (
        "Stumptown Office Supply",
        VendorCategory.SERVICES,
        "6900",
        PaymentMethod.ACH,
        "120.00",
        "880.00",
        8,
    ),
    (
        "Northgate IT Partners",
        VendorCategory.SERVICES,
        "6960",
        PaymentMethod.ACH,
        "1900.00",
        "2600.00",
        6,
    ),
    (
        "Brightline Janitorial",
        VendorCategory.SERVICES,
        "6970",
        PaymentMethod.ACH,
        "1450.00",
        "1720.00",
        6,
    ),
    (
        "Critter Guard Pest Control",
        VendorCategory.SERVICES,
        "6980",
        PaymentMethod.CHECK,
        "260.00",
        "410.00",
        6,
    ),
    (
        "Crown Linen & Uniform",
        VendorCategory.SERVICES,
        "6990",
        PaymentMethod.ACH,
        "380.00",
        "690.00",
        12,
    ),
    (
        "Metro Waste Haulers",
        VendorCategory.SERVICES,
        "6240",
        PaymentMethod.ACH,
        "510.00",
        "790.00",
        6,
    ),
    (
        "Rose City Tire & Auto",
        VendorCategory.MAINTENANCE,
        "6430",
        PaymentMethod.CHECK,
        "220.00",
        "2900.00",
        5,
    ),
    (
        "Talent Bridge Staffing",
        VendorCategory.SERVICES,
        "6160",
        PaymentMethod.ACH,
        "1800.00",
        "5600.00",
        10,
    ),
    (
        "Keystone Scale & Calibration",
        VendorCategory.MAINTENANCE,
        "6630",
        PaymentMethod.CHECK,
        "180.00",
        "940.00",
        2,
    ),
    (
        "Harborview Sign Co.",
        VendorCategory.SERVICES,
        "6000",
        PaymentMethod.CHECK,
        "400.00",
        "2400.00",
        2,
    ),
    (
        "Northwest Grocers Association",
        VendorCategory.SERVICES,
        "6930",
        PaymentMethod.CHECK,
        "650.00",
        "1800.00",
        1,
    ),
    (
        "Salem Pallet Recyclers",
        VendorCategory.SERVICES,
        "5150",
        PaymentMethod.ACH,
        "300.00",
        "1200.00",
        8,
    ),
    (
        "Coastline Shredding",
        VendorCategory.SERVICES,
        "6900",
        PaymentMethod.ACH,
        "95.00",
        "240.00",
        6,
    ),
    (
        "Everbright Electric Contractors",
        VendorCategory.MAINTENANCE,
        "6620",
        PaymentMethod.CHECK,
        "700.00",
        "5400.00",
        3,
    ),
    (
        "Tri-County Health Permits",
        VendorCategory.SERVICES,
        "6060",
        PaymentMethod.CHECK,
        "180.00",
        "900.00",
        2,
    ),
    (
        "CloudLedger Software",
        VendorCategory.SERVICES,
        "6935",
        PaymentMethod.ACH,
        "420.00",
        "640.00",
        6,
    ),
    (
        "Pinnacle Payroll Services",
        VendorCategory.SERVICES,
        "6190",
        PaymentMethod.ACH,
        "310.00",
        "420.00",
        6,
    ),
    (
        "Willamette Sanitation Supply",
        VendorCategory.SERVICES,
        "6970",
        PaymentMethod.ACH,
        "160.00",
        "980.00",
        8,
    ),
    (
        "Cascade Trade Show Group",
        VendorCategory.SERVICES,
        "6010",
        PaymentMethod.CHECK,
        "1200.00",
        "4800.00",
        1,
    ),
    (
        "Mill Creek Temp Controls",
        VendorCategory.MAINTENANCE,
        "6600",
        PaymentMethod.ACH,
        "350.00",
        "2100.00",
        3,
    ),
    (
        "Emerald City Cold Storage",
        VendorCategory.SERVICES,
        "6330",
        PaymentMethod.ACH,
        "2200.00",
        "3900.00",
        6,
    ),
    (
        "Oregon Tilth Certification",
        VendorCategory.SERVICES,
        "6060",
        PaymentMethod.CHECK,
        "750.00",
        "1600.00",
        1,
    ),
    (
        "Portland Fleet Wash",
        VendorCategory.SERVICES,
        "6430",
        PaymentMethod.ACH,
        "180.00",
        "420.00",
        6,
    ),
    (
        "Lewis & Clark Legal Services",
        VendorCategory.PROFESSIONAL,
        "6950",
        PaymentMethod.CHECK,
        "900.00",
        "3100.00",
        1,
    ),
)

CLERKS: Final = ("jmorales", "kpatel", "lnguyen")


def _address(
    rng: ScenarioRng, cities: tuple[tuple[str, str, str], ...]
) -> tuple[str, str, str, str]:
    city, region, zip_prefix = rng.choice(cities)
    return (
        f"{rng.integer(100, 9800)} {rng.choice(_STREETS)}",
        city,
        region,
        f"{zip_prefix}{rng.integer(0, 99):02d}",
    )


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())[:18]


class _UniqueDigits:
    """Unique 4-digit tax-id suffixes, avoiding values reserved by documented facts."""

    def __init__(self, rng: ScenarioRng, reserved: set[str]) -> None:
        self._pool = [f"{n:04d}" for n in range(1000, 10000) if f"{n:04d}" not in reserved]
        self._pool = rng.shuffled(self._pool)

    def take(self) -> str:
        return self._pool.pop()


def _customer(
    *,
    code: str,
    name: str,
    address: tuple[str, str, str, str],
    email: str,
    tax: str | None,
    currency: Currency = USD,
    terms: int,
    active: bool = True,
    created_on: date,
) -> Party:
    return Party(
        party_type=PartyType.CUSTOMER,
        code=code,
        name=name,
        address_line1=address[0],
        city=address[1],
        region=address[2],
        postal_code=address[3],
        country="US" if currency == USD else "DE",
        email=email,
        tax_id_last4=tax,
        default_currency=currency,
        payment_terms_days=terms,
        is_active=active,
        created_on=created_on,
    )


def build_customers(rng: ScenarioRng) -> list[CustomerProfile]:
    tax = _UniqueDigits(rng.child("tax"), reserved={"2210", "9043"})
    code_pool = [f"C-{n:04d}" for n in range(1, 431)]
    reserved_codes = {
        k.GREEN_VALLEY,
        k.GREEN_VALLEY_DUPLICATE,
        k.GREEN_VALLEY_STORE_2,
        k.TN05_CUSTOMER,
        k.ROSE_CITY,
        k.ALPENKOST,
        k.CEDAR_AND_SALT,
    }
    free_codes = rng.child("codes").shuffled([c for c in code_pool if c not in reserved_codes])
    profiles: list[CustomerProfile] = []

    def old_date(r: ScenarioRng) -> date:
        return r.date_between(date(2011, 3, 1), date(2025, 9, 30))

    # ---------------------------------------------------------------- documented customers
    anchor_rng = rng.child("anchors")
    profiles.append(
        CustomerProfile(
            _customer(
                code=k.GREEN_VALLEY,
                name="Green Valley Co-op",
                address=("1220 SE Hawthorne Blvd", "Portland", "OR", "97214"),
                email="ap@greenvalley.coop",
                tax=tax.take(),
                terms=30,
                created_on=date(2014, 5, 12),
            ),
            Segment.GROCER,
            Warehouse.PORTLAND,
            PaymentMethod.CHECK,
        )
    )
    profiles.append(
        CustomerProfile(
            _customer(
                code=k.GREEN_VALLEY_STORE_2,
                name="GREEN VALLEY COOP #2",
                address=("7815 N Lombard St", "Portland", "OR", "97203"),
                email="store2.accounts@greenvalley.coop",
                tax=tax.take(),
                terms=30,
                created_on=date(2021, 8, 3),
            ),
            Segment.GROCER,
            Warehouse.PORTLAND,
            PaymentMethod.CHECK,
        )
    )
    profiles.append(
        CustomerProfile(
            _customer(
                code=k.ROSE_CITY,
                name="Rose City Market Hall",
                address=("405 NE Couch St", "Portland", "OR", "97232"),
                email="payables@rosecitymarkethall.com",
                tax=tax.take(),
                terms=30,
                created_on=old_date(anchor_rng),
            ),
            Segment.GROCER,
            Warehouse.PORTLAND,
            PaymentMethod.ACH,
        )
    )
    profiles.append(
        CustomerProfile(
            _customer(
                code=free_codes.pop(),
                name="Mountain Grocers Inc.",
                address=("61535 S Hwy 97", "Bend", "OR", "97702"),
                email="office@mountaingrocersbend.com",
                tax="2210",
                terms=30,
                created_on=old_date(anchor_rng),
            ),
            Segment.GROCER,
            Warehouse.PORTLAND,
            PaymentMethod.CHECK,
        )
    )
    profiles.append(
        CustomerProfile(
            _customer(
                code=free_codes.pop(),
                name="Mountain Grocers LLC",
                address=("1450 W Main St", "Boise", "ID", "83702"),
                email="ap@mtngrocersidaho.com",
                tax="9043",
                terms=30,
                created_on=old_date(anchor_rng),
            ),
            Segment.GROCER,
            Warehouse.BOISE,
            PaymentMethod.ACH,
        )
    )
    profiles.append(
        CustomerProfile(
            _customer(
                code=k.TN05_CUSTOMER,
                name="Saltbox Kitchen",
                address=("2214 NW Thurman St", "Portland", "OR", "97210"),
                email="owner@saltboxkitchen.com",
                tax=tax.take(),
                terms=15,
                created_on=old_date(anchor_rng),
            ),
            Segment.RESTAURANT,
            Warehouse.PORTLAND,
            PaymentMethod.CHECK,
        )
    )
    profiles.append(
        CustomerProfile(
            _customer(
                code=k.CEDAR_AND_SALT,
                name="Cedar & Salt Bistro",
                address=("3340 SE Belmont St", "Portland", "OR", "97214"),
                email="books@cedarandsalt.com",
                tax=tax.take(),
                terms=15,
                created_on=date(2019, 4, 22),
            ),
            Segment.RESTAURANT,
            Warehouse.PORTLAND,
            PaymentMethod.CHECK,
        )
    )
    profiles.append(
        CustomerProfile(
            _customer(
                code=k.ALPENKOST,
                name="Alpenkost GmbH",
                address=("Leopoldstrasse 118", "Munich", "BY", "80802"),
                email="kreditoren@alpenkost.de",
                tax=None,
                currency=EUR,
                terms=90,
                created_on=date(2023, 10, 9),
            ),
            Segment.EXPORT,
            Warehouse.PORTLAND,
            PaymentMethod.WIRE,
        )
    )

    # ---------------------------------------------------------------- generated customers
    grocer_rng = rng.child("grocers")
    regions = {
        Warehouse.PORTLAND: _OR_CITIES,
        Warehouse.SEATTLE: _WA_CITIES,
        Warehouse.BOISE: _ID_CITIES,
    }
    grocer_warehouses = [Warehouse.PORTLAND] * 16 + [Warehouse.SEATTLE] * 12 + [Warehouse.BOISE] * 6
    for name, warehouse in zip(_GROCERS, grocer_warehouses, strict=True):
        profiles.append(
            CustomerProfile(
                _customer(
                    code=free_codes.pop(),
                    name=name,
                    address=_address(grocer_rng, regions[warehouse]),
                    email=f"ap@{_slug(name)}.com",
                    tax=tax.take(),
                    terms=30,
                    created_on=old_date(grocer_rng),
                ),
                Segment.GROCER,
                warehouse,
                PaymentMethod.ACH if grocer_rng.chance(55, 100) else PaymentMethod.CHECK,
            )
        )

    restaurant_rng = rng.child("restaurants")
    words = list(_RESTAURANT_WORDS)
    if len(words) != len(set(words)) or len(words) < 123:
        raise ScenarioConsistencyError("restaurant name words must be unique and sufficient")
    for index, word in enumerate(words[:123]):
        kind = _RESTAURANT_TYPES[index % len(_RESTAURANT_TYPES)]
        name = f"{word} {kind}"
        warehouse = (Warehouse.PORTLAND, Warehouse.PORTLAND, Warehouse.SEATTLE, Warehouse.BOISE)[
            index % 4
        ]
        profiles.append(
            CustomerProfile(
                _customer(
                    code=free_codes.pop(),
                    name=name,
                    address=_address(restaurant_rng, regions[warehouse]),
                    email=f"billing@{_slug(name)}.com",
                    tax=tax.take(),
                    terms=15,
                    created_on=old_date(restaurant_rng),
                ),
                Segment.RESTAURANT,
                warehouse,
                PaymentMethod.CHECK if restaurant_rng.chance(60, 100) else PaymentMethod.ACH,
            )
        )

    dormant_rng = rng.child("dormant")
    for index, word in enumerate(
        (
            "Catering Collective",
            "Farmers Guild",
            "School Nutrition Services",
            "Hospital Foodservice",
            "Event Kitchens",
            "Campus Dining",
        )
    ):
        city = ("Portland", "Seattle", "Boise", "Eugene", "Tacoma", "Salem")[index]
        name = f"{city} {word}"
        warehouse = (Warehouse.PORTLAND, Warehouse.SEATTLE, Warehouse.BOISE)[index % 3]
        profiles.append(
            CustomerProfile(
                _customer(
                    code=free_codes.pop(),
                    name=name,
                    address=_address(dormant_rng, regions[warehouse]),
                    email=f"ap@{_slug(name)}.org",
                    tax=tax.take(),
                    terms=30,
                    created_on=old_date(dormant_rng),
                ),
                Segment.DORMANT,
                warehouse,
                PaymentMethod.CHECK,
            )
        )

    historical_rng = rng.child("historical")
    seen: set[str] = set()
    for _ in range(236):
        while True:
            first = historical_rng.choice(_HISTORICAL_WORDS_A)
            second = historical_rng.choice(_HISTORICAL_WORDS_B)
            name = f"{first} {second} {historical_rng.choice(_HISTORICAL_TYPES)}"
            if name not in seen:
                seen.add(name)
                break
        warehouse = historical_rng.choice(list(Warehouse))
        profiles.append(
            CustomerProfile(
                _customer(
                    code=free_codes.pop(),
                    name=name,
                    address=_address(historical_rng, regions[warehouse]),
                    email=f"ap@{_slug(name)}.com",
                    tax=tax.take(),
                    terms=30,
                    active=False,
                    created_on=historical_rng.date_between(date(2009, 1, 5), date(2022, 12, 20)),
                ),
                Segment.HISTORICAL,
                warehouse,
                PaymentMethod.CHECK,
            )
        )

    codes = [p.party.code for p in profiles]
    if len(set(codes)) != len(codes):
        raise ScenarioConsistencyError("duplicate customer codes")
    return sorted(profiles, key=lambda p: p.party.code)


def build_vendors(rng: ScenarioRng) -> list[VendorProfile]:
    tax = _UniqueDigits(rng.child("tax"), reserved={"7781"})
    reserved = {k.PCP_VENDOR, k.PCP_DUPLICATE_VENDOR, k.SUMMIT_VENDOR}
    free_codes = rng.child("codes").shuffled(
        [f"V-{n}" for n in range(1001, 1300) if f"V-{n}" not in reserved]
    )
    profiles: list[VendorProfile] = []
    producer_rng = rng.child("producers")
    for name in _PRODUCERS:
        city, region, zip_code = producer_rng.choice(_OR_CITIES + _WA_CITIES + _ID_CITIES)
        party = Party(
            party_type=PartyType.VENDOR,
            code=free_codes.pop(),
            name=name,
            address_line1=f"{producer_rng.integer(100, 42000)} {producer_rng.choice(_STREETS)}",
            city=city,
            region=region,
            postal_code=f"{zip_code}{producer_rng.integer(0, 99):02d}",
            country="US",
            email=f"ar@{_slug(name)}.com",
            tax_id_last4=tax.take(),
            default_currency=USD,
            payment_terms_days=producer_rng.choice((15, 30, 30, 30)),
            is_active=True,
            created_on=producer_rng.date_between(date(2012, 1, 9), date(2025, 6, 30)),
        )
        profiles.append(
            VendorProfile(
                party,
                VendorCategory.PRODUCER,
                "1300",
                PaymentMethod.CHECK if producer_rng.chance(35, 100) else PaymentMethod.ACH,
                producer_rng.choice(CLERKS),
                Decimal("3800.00"),
                Decimal("15800.00"),
                producer_rng.integer(15, 21),
            )
        )

    other_rng = rng.child("other")
    for name, category, account, method, low, high, count in _OTHER_VENDORS:
        if name == "Pacific Coast Packaging LLC":
            code, address, tax_last4 = (
                k.PCP_VENDOR,
                ("4410 NW Front Ave Ste 200", "Portland", "OR", "97209"),
                "7781",
            )
        elif name == "Summit Refrigeration Services":
            code, address, tax_last4 = (
                k.SUMMIT_VENDOR,
                ("8120 SE Foster Rd", "Portland", "OR", "97206"),
                tax.take(),
            )
        else:
            code, address, tax_last4 = (
                free_codes.pop(),
                _address(other_rng, _OR_CITIES + _WA_CITIES),
                tax.take(),
            )
        terms = (
            0
            if category is VendorCategory.LANDLORD
            else (20 if category is VendorCategory.UTILITY else 30)
        )
        party = Party(
            party_type=PartyType.VENDOR,
            code=code,
            name=name,
            address_line1=address[0],
            city=address[1],
            region=address[2],
            postal_code=address[3],
            country="US",
            email=f"billing@{_slug(name)}.com",
            tax_id_last4=tax_last4,
            default_currency=USD,
            payment_terms_days=terms,
            is_active=True,
            created_on=other_rng.date_between(date(2010, 6, 1), date(2025, 3, 31)),
        )
        profiles.append(
            VendorProfile(
                party,
                category,
                account,
                method,
                other_rng.choice(CLERKS),
                Decimal(low),
                Decimal(high),
                count,
            )
        )
    return sorted(profiles, key=lambda p: p.party.code)
