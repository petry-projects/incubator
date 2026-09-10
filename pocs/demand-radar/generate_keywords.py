#!/usr/bin/env python3
"""
DemandRadar — keyword generator (spike, phase 0).

Produces the idea SPACE: domain x tool-type combinations across 25 verticals,
each tagged with discovery_channel + vertical_dynamics (#44). Combinatorial by
design — most combos will be nonsense or already-served and get filtered by the
supply pass; the point is broad, repeatable coverage so real gaps surface.

Output: output/keywords.jsonl  (one {keyword, vertical, discovery_channel, ...} per line)

  python generate_keywords.py            # ~10k+ keywords across 25 verticals
  python generate_keywords.py --tools 20 # cap tool-types per domain
"""

import argparse
import json
import os

# Shared tool-types (the "app shape"). Ordered so --tools N takes the most natural first.
TOOLS = [
    "tracker", "planner", "log", "journal", "timer", "reminder", "checklist",
    "manager", "organizer", "calculator", "counter", "generator", "scanner",
    "converter", "logbook", "dashboard", "coach", "guide", "companion", "finder",
    "app", "buddy", "hub", "assistant",
    # need-shapes beyond the "tool" grid — data-loss / portability pain (e.g. BlockVault = game-save backup)
    "backup", "restore", "sync", "versioning", "migration", "transfer",
]

# vertical -> (discovery_channel, vertical_dynamics, [domain nouns])
VERTICALS = {
    "gaming-companions": ("community", "gap-generating", [
        "valheim base", "speedrun", "combo", "couch co op", "gacha pity", "loadout",
        "mod", "raid dps", "fishing spot", "boss fight", "achievement", "skill tree",
        "crafting recipe", "seed", "farm layout", "pvp rank", "clan war", "loot table",
        "quest", "controller mapping"]),
    "tabletop-ttrpg": ("community", "gap-generating", [
        "initiative", "character sheet", "dice", "encounter", "loot", "campaign note",
        "npc", "spell", "monster", "battle map", "session recap", "inventory",
        "hex crawl", "dungeon", "faction", "condition", "wild magic", "treasure",
        "combat", "downtime"]),
    "student-education": ("app-store", "saturated", [
        "flashcard", "spaced repetition", "lecture", "assignment", "citation", "study",
        "exam", "homework", "gpa", "note taking", "vocabulary", "reading", "essay",
        "thesis", "lab report", "syllabus", "tutoring", "quiz", "handwriting", "formula"]),
    "creator-content": ("app-store", "gap-generating", [
        "thumbnail", "teleprompter", "caption", "watermark", "soundboard", "green screen",
        "podcast", "voiceover", "b-roll", "content calendar", "hook", "hashtag",
        "carousel", "reel", "subtitle", "color grade", "royalty free", "brand kit",
        "stream overlay", "collab"]),
    "everyday-utilities": ("app-store", "saturated", [
        "unit", "decibel", "level", "tip", "qr", "white noise", "measure", "compass",
        "flashlight", "magnifier", "clipboard", "battery", "wifi", "speed test",
        "screen mirror", "file transfer", "password", "barcode", "ruler", "stopwatch"]),
    "health-fitness": ("app-store", "saturated", [
        "macro", "water", "stretching", "posture", "walking pad", "breathwork", "step",
        "workout", "rep", "interval", "mobility", "recovery", "hydration", "calorie",
        "protein", "sleep", "heart rate", "running", "cycling cadence", "warmup"]),
    "mental-wellness": ("app-store", "mixed", [
        "mood", "gratitude", "anxiety", "meditation", "habit", "cbt", "trigger",
        "panic", "affirmation", "journaling", "burnout", "self care", "grounding",
        "therapy note", "urge", "sobriety", "stress", "focus", "worry", "reflection"]),
    "finance-money": ("app-store", "saturated", [
        "budget", "bill", "subscription", "expense split", "receipt", "net worth", "debt",
        "savings", "allowance", "invoice", "tax", "crypto", "dividend", "mileage",
        "tip out", "cash envelope", "loan", "spending", "paycheck", "sinking fund"]),
    "parenting-kids": ("app-store", "mixed", [
        "chore", "screen time", "potty", "baby feeding", "allowance", "contraction",
        "diaper", "nap", "growth", "milestone", "carpool", "babysitter", "reward",
        "bedtime", "tooth", "vaccine", "school lunch", "reading log", "behavior", "pumping"]),
    "pets-animals": ("app-store", "mixed", [
        "pet health", "dog walk", "feeding", "aquarium", "reptile", "horse", "cat litter",
        "vet visit", "grooming", "training", "medication", "weight", "shedding",
        "bird", "chicken coop", "bee hive", "puppy", "kitten", "leash", "treat"]),
    "food-cooking": ("app-store", "saturated", [
        "recipe", "meal", "pantry", "grocery", "sourdough", "coffee brewing", "smoker bbq",
        "canning", "fermentation", "wine", "cocktail", "spice", "leftover", "macros",
        "portion", "baking", "kombucha", "cheese", "hot sauce", "cast iron"]),
    "home-diy": ("app-store", "mixed", [
        "home inventory", "plant watering", "cleaning", "moving", "firewood", "generator",
        "tool", "paint color", "renovation", "warranty", "appliance", "pantry stock",
        "chore rotation", "septic", "water filter", "hvac filter", "lawn", "pest",
        "storage bin", "declutter"]),
    "gardening-plants": ("app-store", "mixed", [
        "seed starting", "watering", "harvest", "compost", "pest", "frost", "bloom",
        "succulent", "orchid", "hydroponic", "raised bed", "crop rotation", "soil ph",
        "fertilizer", "pruning", "greenhouse", "germination", "companion planting",
        "houseplant", "bonsai"]),
    "travel-outdoors": ("app-store", "saturated", [
        "packing", "itinerary", "travel journal", "jet lag", "roadtrip", "campsite",
        "hiking trail", "national park", "flight", "layover", "visa", "currency",
        "backpacking", "tide", "trail condition", "gear", "fuel stop", "border wait",
        "souvenir", "passport"]),
    "accessibility-seniors": ("app-store", "gap-generating", [
        "medication", "hearing", "magnifier", "pill", "fall", "large button",
        "voice note", "emergency contact", "reminder call", "blood pressure",
        "glucose", "appointment", "caregiver", "symptom", "vision test", "tremor",
        "mobility", "hydration", "loneliness", "memory"]),
    "small-business": ("app-store", "mixed", [
        "invoice", "mileage", "appointment", "inventory count", "time clock", "estimate",
        "receipt", "client", "quote", "shift", "tip pool", "petty cash", "purchase order",
        "commission", "lead", "booking", "expense", "payroll", "vendor", "contract"]),
    "productivity-work": ("app-store", "saturated", [
        "task", "meeting note", "standup", "okr", "time block", "pomodoro", "email",
        "follow up", "decision", "one on one", "retro", "kanban", "deep work",
        "context switch", "handoff", "backlog", "daily plan", "focus", "distraction", "goal"]),
    "hobbies-crafts": ("app-store", "mixed", [
        "knitting", "crochet", "quilting", "cross stitch", "woodworking cut", "3d print",
        "resin", "candle", "soap", "pottery", "beading", "embroidery", "scrapbook",
        "model kit", "leather", "calligraphy", "origami", "sewing pattern", "yarn stash",
        "diamond painting"]),
    "music-audio": ("app-store", "mixed", [
        "metronome", "tuner", "chord", "setlist", "practice", "ear training", "scale",
        "tab", "backing track", "gig", "lyric", "sample", "bpm", "vocal warmup",
        "sheet music", "fretboard", "drum pattern", "mixing", "rehearsal", "songwriting"]),
    "auto-vehicle": ("app-store", "mixed", [
        "fuel", "maintenance", "mileage", "oil change", "tire", "service", "road trip",
        "parking", "toll", "car wash", "recall", "vin", "ev charging", "fuel economy",
        "repair", "part", "registration", "dashcam", "trailer", "fleet"]),
    "events-social": ("app-store", "mixed", [
        "wedding", "party", "guest list", "seating", "potluck", "gift", "rsvp",
        "secret santa", "reunion", "fundraiser", "bachelorette", "birthday", "registry",
        "volunteer", "carpool", "group cost split", "itinerary", "meetup", "toast", "playlist"]),
    "faith-spiritual": ("app-store", "mixed", [
        "bible reading", "prayer", "devotional", "fasting", "scripture memory", "sermon note",
        "rosary", "gratitude", "tithing", "meditation", "quran", "torah", "worship set",
        "small group", "mission trip", "verse", "examen", "liturgy", "retreat", "journal"]),
    "fashion-beauty": ("app-store", "mixed", [
        "outfit", "wardrobe", "capsule closet", "skincare routine", "nail", "hair",
        "makeup", "size", "thrift", "perfume", "color analysis", "laundry care",
        "shoe", "jewelry", "tailoring", "lash", "brow", "self tan", "packing outfit", "style"]),
    "niche-sports": ("community", "mixed", [
        "disc golf", "pickleball", "climbing", "cycling maintenance", "surf", "spearfishing",
        "bouldering", "trail run", "kayak", "archery", "skateboard", "ski wax",
        "golf handicap", "tennis string", "bowling", "darts", "table tennis", "fencing",
        "triathlon", "rowing"]),
    "collectors-hobbies": ("community", "gap-generating", [
        "trading card", "coin", "stamp", "vinyl record", "comic", "sneaker", "lego",
        "funko", "wine cellar", "whiskey", "watch", "gun", "sports card grade", "pin",
        "action figure", "board game shelf", "book", "amiibo", "hot wheels", "pokemon card"]),
}


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--out", default=os.path.join(here, "output", "keywords.jsonl"))
    ap.add_argument("--tools", type=int, default=len(TOOLS))
    args = ap.parse_args()

    tools = TOOLS[: args.tools]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    n = 0
    per_vertical = {}
    with open(args.out, "w", encoding='utf-8') as f:
        for vert, (channel, dyn, domains) in VERTICALS.items():
            c = 0
            # Dedup WITHIN a vertical only. A phrase that recurs across verticals is a
            # distinct classification (e.g. "medication tracker" in pets vs. seniors), so a
            # global set would drop the second vertical's valid record entirely.
            seen = set()
            for dom in domains:
                for tool in tools:
                    kw = f"{dom} {tool}"
                    if kw in seen:
                        continue
                    seen.add(kw)
                    f.write(json.dumps({
                        "keyword": kw, "vertical": vert,
                        "discovery_channel": channel, "vertical_dynamics": dyn,
                    }) + "\n")
                    n += 1
                    c += 1
            per_vertical[vert] = c

    print(f"Wrote {n} keywords across {len(VERTICALS)} verticals -> {args.out}")
    for v, c in per_vertical.items():
        print(f"  {v:<24} {c}")


if __name__ == "__main__":
    main()
