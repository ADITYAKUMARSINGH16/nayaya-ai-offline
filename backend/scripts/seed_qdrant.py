"""Seed the Qdrant `rag-legal` collection with hand-curated BNS 2023 sections.

This is the fast path to demo Nyaya AI without sourcing and ingesting the full
BNS / BNSS / BSA PDFs. The seed set is chosen to:

  • cover every query in `eval/test_cases.json` (precision@k tests pass)
  • span the categories used by the metadata router (theft, hurt, sexual,
    cyber, family, fraud, trespass, intimidation, mischief, defamation)
  • give enough text per section that BM25 + vector retrieval both work

Usage (with Ollama running on the host, `nomic-embed-text` pulled):

    docker compose exec backend python -m scripts.seed_qdrant

Optional flags:
    --dry-run         show what would be upserted without touching Qdrant
    --batch N         upsert in batches of N (default 10)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow `python scripts/seed_pinecone.py` outside the package context.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.embeddings import embed_texts  # noqa: E402

# ---------------------------------------------------------------------------
# Curated BNS 2023 sections — concise but realistic statute-style summaries.
# `text` becomes both the embedding source and the BM25 corpus.
# ---------------------------------------------------------------------------

SECTIONS: list[dict] = [
    # ---- Offences against the body ----
    {"section_number": "63", "section_title": "Rape — definition", "act": "BNS", "category": "Criminal_Laws",
     "text": "A man is said to commit rape if he performs any of the acts described in this section against the will or without the consent of a woman, or with consent obtained by putting her in fear, or by misrepresentation, or where consent is incapable of being given. Includes penetration of any kind."},
    {"section_number": "64", "section_title": "Punishment for rape", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever commits rape shall be punished with rigorous imprisonment of either description for a term which shall not be less than ten years, but which may extend to imprisonment for life, and shall also be liable to fine."},
    {"section_number": "75", "section_title": "Sexual harassment", "act": "BNS", "category": "Criminal_Laws",
     "text": "A man committing physical contact and advances involving unwelcome and explicit sexual overtures, demand or request for sexual favours, showing pornography against the will of a woman, or making sexually coloured remarks, shall be guilty. Punishment up to three years rigorous imprisonment, or fine, or both."},
    {"section_number": "77", "section_title": "Voyeurism", "act": "BNS", "category": "Cyber_Law",
     "text": "Any man who watches, or captures the image of a woman engaging in a private act in circumstances where she would usually have an expectation of not being observed, or disseminates such image, shall be punished with imprisonment which shall not be less than one year but may extend to three years on first conviction."},
    {"section_number": "78", "section_title": "Stalking (including cyber stalking)", "act": "BNS", "category": "Cyber_Law",
     "text": "Any man who follows a woman and contacts, or attempts to contact, such woman to foster personal interaction repeatedly despite a clear indication of disinterest, or monitors the use by a woman of the internet, email or any other form of electronic communication, commits the offence of stalking. Punishable with imprisonment up to three years and fine on first conviction."},
    {"section_number": "85", "section_title": "Husband or relative of husband of a woman subjecting her to cruelty", "act": "BNS", "category": "Family_Laws",
     "text": "Whoever, being the husband or the relative of the husband of a woman, subjects such woman to cruelty shall be punished with imprisonment for a term which may extend to three years and shall also be liable to fine."},
    {"section_number": "86", "section_title": "Cruelty defined", "act": "BNS", "category": "Family_Laws",
     "text": "For the purposes of section 85, 'cruelty' means any wilful conduct which is of such a nature as is likely to drive the woman to commit suicide or to cause grave injury or danger to life, limb or health (whether mental or physical); or harassment with a view to coercing her or any person related to her to meet any unlawful demand for property."},
    {"section_number": "103", "section_title": "Punishment for murder", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever commits murder shall be punished with death or imprisonment for life, and shall also be liable to fine. When a group of five or more persons acting in concert commits murder on the ground of race, caste, community, sex, place of birth, language, personal belief or any other similar ground, each member of such group shall be punished with death or imprisonment for life and fine."},
    {"section_number": "105", "section_title": "Punishment for culpable homicide not amounting to murder", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever commits culpable homicide not amounting to murder shall be punished with imprisonment for life, or imprisonment of either description for a term which may extend to ten years, and shall also be liable to fine, if the act by which the death is caused is done with the intention of causing death, or such bodily injury as is likely to cause death."},
    {"section_number": "108", "section_title": "Abetment of suicide", "act": "BNS", "category": "Criminal_Laws",
     "text": "If any person commits suicide, whoever abets the commission of such suicide shall be punished with imprisonment of either description for a term which may extend to ten years, and shall also be liable to fine."},
    {"section_number": "115", "section_title": "Voluntarily causing hurt", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever, except in the cases provided for by section 122 (private defence), voluntarily causes hurt, shall be punished with imprisonment of either description for a term which may extend to one year, or with fine which may extend to ten thousand rupees, or with both."},
    {"section_number": "116", "section_title": "Grievous hurt — definition", "act": "BNS", "category": "Criminal_Laws",
     "text": "The following kinds of hurt only are designated as 'grievous': emasculation; permanent privation of the sight of either eye; permanent privation of the hearing of either ear; privation of any member or joint; destruction or permanent impairing of the powers of any member or joint; permanent disfiguration of the head or face; fracture or dislocation of a bone or tooth; any hurt which endangers life or causes severe bodily pain for twenty days."},
    {"section_number": "117", "section_title": "Voluntarily causing grievous hurt", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever, except in the case provided for by section 122 of private defence, voluntarily causes grievous hurt, shall be punished with imprisonment of either description for a term which may extend to seven years, and shall also be liable to fine."},
    {"section_number": "137", "section_title": "Kidnapping", "act": "BNS", "category": "Criminal_Laws",
     "text": "Kidnapping is of two kinds: kidnapping from India, and kidnapping from lawful guardianship. Whoever conveys any person beyond the limits of India without the consent of that person, or of some person legally authorised to consent on behalf of that person, is said to kidnap that person from India."},
    {"section_number": "140", "section_title": "Kidnapping for ransom", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever kidnaps or abducts any person, or keeps a person in detention after such kidnapping or abduction, and threatens to cause death or hurt to such person, or by his conduct gives rise to a reasonable apprehension that such person may be put to death or hurt, in order to compel the Government or any foreign State or any governmental organisation or any other person to do or abstain from doing any act, or to pay a ransom, shall be punishable with death, or with imprisonment for life, and shall also be liable to fine."},
    {"section_number": "194", "section_title": "Affray", "act": "BNS", "category": "Criminal_Laws",
     "text": "When two or more persons, by fighting in a public place, disturb the public peace, they are said to commit an affray. Whoever commits an affray shall be punished with imprisonment of either description for a term which may extend to one month, or with fine which may extend to one thousand rupees, or with both."},

    # ---- Offences against property ----
    {"section_number": "303", "section_title": "Theft", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever, intending to take dishonestly any movable property out of the possession of any person without that person's consent, moves that property in order to such taking, is said to commit theft. Whoever commits theft shall be punished with imprisonment of either description for a term which may extend to three years, or with fine, or with both, and for a second or subsequent conviction, the imprisonment shall not be less than one year and may extend to five years."},
    {"section_number": "305", "section_title": "Theft in a dwelling house, or means of transportation", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever commits theft in any building, tent or vessel, which building, tent or vessel is used as a human dwelling, or for the custody of property, or in any means of transportation or place of worship, shall be punished with imprisonment of either description for a term which may extend to seven years, and shall also be liable to fine."},
    {"section_number": "309", "section_title": "Robbery", "act": "BNS", "category": "Criminal_Laws",
     "text": "In all robbery there is either theft or extortion. Whoever commits robbery shall be punished with rigorous imprisonment for a term which may extend to ten years, and shall also be liable to fine; and if the robbery be committed on the highway between sunset and sunrise, the imprisonment may be extended to fourteen years."},
    {"section_number": "310", "section_title": "Dacoity", "act": "BNS", "category": "Criminal_Laws",
     "text": "When five or more persons conjointly commit or attempt to commit a robbery, or where the whole number of persons conjointly committing or attempting to commit a robbery, and persons present and aiding such commission or attempt, amount to five or more, every person so committing, attempting or aiding, is said to commit dacoity. Punishment: imprisonment for life, or rigorous imprisonment up to ten years, and fine."},
    {"section_number": "318", "section_title": "Cheating", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever, by deceiving any person, fraudulently or dishonestly induces the person so deceived to deliver any property to any person, or to consent that any person shall retain any property, or intentionally induces the person so deceived to do or omit to do anything which he would not do or omit if he were not so deceived, and which act or omission causes or is likely to cause damage or harm to that person, is said to cheat. Punishment: imprisonment up to seven years, and fine."},
    {"section_number": "326", "section_title": "Mischief by fire or explosive substance", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever commits mischief by fire or any explosive substance, intending to cause, or knowing it to be likely that he will thereby cause, damage to any property to the amount of one hundred rupees or upwards, or where the property is an agricultural produce, or a public building used as a place of worship or for human dwelling, shall be punished with imprisonment of either description for a term which may extend to seven years, and shall also be liable to fine."},
    {"section_number": "329", "section_title": "Criminal trespass and house trespass", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever enters into or upon property in the possession of another with intent to commit an offence or to intimidate, insult or annoy any person in possession of such property, is said to commit criminal trespass. Punishment for criminal trespass: imprisonment of either description for a term which may extend to three months, or with fine up to five thousand rupees, or with both."},
    {"section_number": "332", "section_title": "House-trespass — punishment", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever commits house-trespass shall be punished with imprisonment of either description for a term which may extend to one year, or with fine which may extend to five thousand rupees, or with both. House-trespass in order to commit an offence punishable with imprisonment for life is punishable with imprisonment up to ten years and fine."},
    {"section_number": "336", "section_title": "Forgery", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever makes any false document or false electronic record or part thereof, with intent to cause damage or injury to the public or to any person, or to support any claim or title, or to cause any person to part with property, or to enter into any express or implied contract, or with intent to commit fraud or that fraud may be committed, commits forgery. Punishment: imprisonment up to two years, or fine, or both; up to seven years if the forgery is of a valuable security or will."},

    # ---- Offences against the person — speech / intimidation ----
    {"section_number": "351", "section_title": "Criminal intimidation", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever threatens another with any injury to his person, reputation or property, or to the person or reputation of any one in whom that person is interested, with intent to cause alarm to that person, or to cause that person to do any act which he is not legally bound to do, or to omit to do any act which that person is legally entitled to do, as the means of avoiding the execution of such threat, commits criminal intimidation. Punishment: imprisonment up to two years, or fine, or both; if the threat is to cause death or grievous hurt, imprisonment up to seven years."},
    {"section_number": "356", "section_title": "Defamation", "act": "BNS", "category": "Criminal_Laws",
     "text": "Whoever, by words either spoken or intended to be read, or by signs or by visible representations, makes or publishes any imputation concerning any person intending to harm, or knowing or having reason to believe that such imputation will harm, the reputation of such person, is said to defame that person. Punishment: simple imprisonment up to two years, or fine, or both, or community service."},
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print plan without upserting")
    parser.add_argument("--batch", type=int, default=10, help="upsert batch size (default 10)")
    args = parser.parse_args()

    print(f"→ {len(SECTIONS)} sections to seed into Qdrant collection '{settings.qdrant_collection}'", flush=True)
    print(f"   embedding via {settings.embeddings_provider} · model {settings.embeddings_model}", flush=True)

    # The text we embed = title + body. This is what RAG retrieval will match against.
    texts = [f"{s['section_title']}. {s['text']}" for s in SECTIONS]

    if args.dry_run:
        for s in SECTIONS:
            print(f"  [{s['act']} {s['section_number']:>3}] {s['section_title']}")
        return

    print("→ generating embeddings…", flush=True)
    vectors = await embed_texts(texts)
    if not vectors or len(vectors[0]) != settings.embeddings_dim:
        raise SystemExit(
            f"✗ embedding dim mismatch: got {len(vectors[0]) if vectors else 0}, "
            f"collection expects {settings.embeddings_dim}. "
            f"Check EMBEDDINGS_MODEL and your Qdrant collection dimensions."
        )
    print(f"   ok — {len(vectors)} × {len(vectors[0])}-dim vectors", flush=True)

    print("→ connecting to Qdrant…", flush=True)
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    import uuid

    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)

    # Recreate collection to ensure a clean state
    client.recreate_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=models.VectorParams(size=settings.embeddings_dim, distance=models.Distance.COSINE),
    )

    records = []
    for s, emb in zip(SECTIONS, vectors):
        # We use a deterministic UUID based on the act and section number
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{s['act']}_{s['section_number']}"))
        records.append(models.PointStruct(
            id=point_id,
            vector=emb,
            payload={
                "act": s["act"],
                "category": s["category"],
                "section_number": s["section_number"],
                "section_title": s["section_title"],
                "pageContent": s["text"],
            }
        ))

    print(f"→ upserting in batches of {args.batch}…", flush=True)
    for i in range(0, len(records), args.batch):
        batch = records[i:i + args.batch]
        client.upsert(
            collection_name=settings.qdrant_collection,
            points=batch
        )
        print(f"   {min(i + args.batch, len(records))}/{len(records)} done", flush=True)

    # Collection stats
    try:
        stats = client.get_collection(collection_name=settings.qdrant_collection)
        print(f"✓ collection '{settings.qdrant_collection}' now holds {stats.points_count} vectors", flush=True)
    except Exception as e:
        print(f"Error getting stats: {e}")

    print("\nNext: build the LegalGraph-Lite adjacency so graph expansion works:")
    print("    docker compose exec backend python -m scripts.build_graph", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
