# Rich Plan schema reference

`create_plan` and `update_plan` accept a `plan` object that must validate as `PlanDraft`.
Optional fields may be omitted or empty. Never fabricate data merely to fill fields.

```text
PlanDraft
├── title: string (required)
├── subtitle?: string
├── requirements: TravelRequirements
├── overview?: string
├── weather_summary?: string
├── weather_details[]
│   ├── month?: string
│   └── summary: string
├── weather_tip?: string
├── schedule[]
│   ├── day: integer >= 1
│   ├── date?: YYYY-MM-DD
│   ├── title?: string
│   ├── city: string
│   ├── summary?: string
│   ├── activities[]
│   │   ├── period?: string
│   │   ├── start_time?: HH:MM
│   │   ├── end_time?: HH:MM
│   │   ├── title: string
│   │   ├── description?: string
│   │   ├── route[]
│   │   ├── highlights[]
│   │   ├── photo_spots[]
│   │   ├── pois[] {name, address?}
│   │   ├── location?: string
│   │   ├── transportation?: string
│   │   ├── estimated_cost?: string
│   │   ├── booking_notes[]
│   │   ├── tips[]
│   │   ├── alternatives[]
│   │   └── source_url?: string
│   ├── transportation[]
│   │   └── {from_location, to_location, mode, estimated_duration_minutes?, estimated_cost?}
│   ├── accommodation?: {area, type, name?, estimated_cost?}
│   └── day_tips[]
├── transportation_guide[]
│   └── {from_location, to_location, mode?, duration?, price?, departure_station?, arrival_station?, schedule?, suggestion?}
├── food_recommendations[]
│   └── {name, category?, area?, address?, recommended_dishes[], price_reference?, description?, best_time?, tips[], source_url?}
├── food_route[]
├── attraction_guides[]
│   └── {name, introduction?, history?, highlights[], recommended_duration?, ticket_info?, opening_hours?, booking_info?, photo_spots[], best_visit_time?, tips[], source_url?}
├── accommodation_recommendations[]
│   └── {name?, area?, address?, type?, price_reference?, description?, tips[], source_url?}
├── budget_breakdown[] {item, per_person}
├── budget_total?: string
├── booking_tips[]
├── transportation_tips[]
├── clothing_tips[]
├── photo_tips[]
├── budget_tips[]
├── warnings[]
└── assumptions[]
```

## TravelRequirements

```text
origin?: string
destinations: string[]
start_date?: YYYY-MM-DD
end_date?: YYYY-MM-DD
duration_days?: integer 1..60
traveler_count?: integer 1..50
budget_per_person_cny?: integer
pace?: relaxed | moderate | intense | comfortable
must_visit: string[]
exclude: string[]
accommodation_preference?: string
notes?: string
```

The Domain Tool overwrites `plan.requirements` with canonical requirements and assigns stable IDs/dates where applicable, so do not invent ID values.

## Quality target

A complete Plan should preserve practically useful research information: daily timing/routes, transport, costs as text, booking/opening notes, photo spots, alternatives, food, attraction deep-dives, accommodation, budget and preparation/warnings. Do not compress useful research just because the object is JSON-shaped.
