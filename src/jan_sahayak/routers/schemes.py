from fastapi import APIRouter, Depends, File, Query, UploadFile, Request, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jan_sahayak.database import get_db
from jan_sahayak.exceptions import SchemeNotFoundError
from jan_sahayak.logger import get_logger
from jan_sahayak.models.scheme import Scheme
from jan_sahayak.schemas.api import MessageResponse, SchemeCreate, SchemeListResponse, SchemeResponse
from jan_sahayak.services.sarvam import sarvam_service
from jan_sahayak.services.scheme_engine import scheme_engine
from jan_sahayak.limiter import limiter
from jan_sahayak.services.auth import get_current_user
from jan_sahayak.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/api/schemes", tags=["Schemes"])


@router.post("/digitize")
@limiter.limit("10/minute")
async def digitize_document(
    request: Request,
    file: UploadFile = File(..., description="Document image or PDF (Aadhaar, PAN, income cert)"),
    current_user: User = Depends(get_current_user),
):

    """
    Upload a document (Aadhaar card, PAN card, income certificate, etc.)
    and extract structured profile data using Sarvam Document Digitization API.

    Returns extracted_data dict with fields like name, state, annual_income, etc.
    """
    # Validate MIME type
    allowed_mimes = ["application/pdf", "image/png", "image/jpeg", "image/jpg"]
    if file.content_type not in allowed_mimes:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Allowed: PDF, PNG, JPEG."
        )

    # Validate file size (5MB limit)
    MAX_FILE_SIZE = 5 * 1024 * 1024
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds the 5MB limit."
        )

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="Empty file uploaded."
        )


    try:
        raw_result = await sarvam_service.digitize_document(file_bytes, file_name=file.filename or "document")
    except Exception as e:
        logger.error(f"Document digitization failed: {e}", exc_info=True)
        return {"extracted_data": {}, "raw": {}, "error": str(e)}

    # Use the LLM directly for document extraction — NO regex (regex matches false positives
    # on document text like zip codes being treated as income, or abbreviations as categories)
    extracted = {}
    try:
        data = raw_result if isinstance(raw_result, dict) else {}
        markdown_text = data.get("markdown")
        
        if markdown_text:
            # Strip base64-encoded images — they are huge (90K+ tokens) and useless for text extraction
            import re
            clean_text = re.sub(r'!\[.*?\]\(data:image/[^)]+\)', '', markdown_text)
            # Also strip any remaining bare base64 blobs
            clean_text = re.sub(r'data:image/[a-zA-Z]+;base64,[A-Za-z0-9+/=\n]+', '', clean_text)
            # Strip italic OCR descriptions (QR code descriptions, image captions, etc.)
            clean_text = re.sub(r'\*[^*]{20,}\*', '', clean_text)
            # Strip "[image removed]" and "[base64 removed]" placeholders
            clean_text = re.sub(r'\[(?:image|base64) removed\]', '', clean_text)
            # Strip lines that are just noise
            noise_patterns = [
                r'Shot on .*', r'Powered by .*', r'Unhewn stone.*',
                r'काहीतरी.*', r'सांगूया.*', r'कदाचित्.*', r'नामदेव\n',
            ]
            for np in noise_patterns:
                clean_text = re.sub(np, '', clean_text)
            # Strip excessive whitespace
            clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
            
            logger.info(f"📄 Document text (cleaned, first 800 chars): {clean_text[:800]}")
            logger.info(f"📊 Text length: original={len(markdown_text)} chars, cleaned={len(clean_text)} chars")
            
            import json as json_mod
            doc_prompt = """You are extracting profile data from an Indian identity document.

Extract ONLY fields that are EXPLICITLY written on the document. Return a JSON object:
{"name": "...", "state": "...", "district": "...", "annual_income": null, "category": null, "occupation": null, "age": N, "gender": "...", "document_type": "..."}

Rules:
- name: Person's full name (NOT parent/spouse after S/O, W/O, D/O)
- state: Standardized (OD=Odisha, UP=Uttar Pradesh, etc). null if not on doc.
- age: Calculate from DOB. 2026 minus birth year. DOB 12/07/1991 → age=34. 
- gender: Infer from S/O=male, D/O=female, W/O=female
- annual_income: ONLY from income certificates. null for PAN/Aadhaar/DL.
- category: ONLY from caste certificates. null for PAN/Aadhaar/DL.
- document_type: Identify what kind of document this is. Strictly one of: "Aadhaar Card", "Bank Account Details", "Land Ownership Records", "Ration Card", "Income Certificate", "BPL Card", "Job Card", "Caste Certificate", or "Other".
- Set fields to null if NOT on the document. Do NOT guess.
- Return ONLY valid JSON. No markdown, no explanation."""

            messages = [
                {"role": "system", "content": doc_prompt},
                {"role": "user", "content": clean_text},
            ]

            response_text = await sarvam_service.chat(messages, temperature=0.0)
            logger.info(f"🤖 LLM raw response ({len(response_text)} chars): {response_text}")

            # Parse the JSON response
            clean_json = response_text.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json[7:]
            if clean_json.startswith("```"):
                clean_json = clean_json[3:]
            if clean_json.endswith("```"):
                clean_json = clean_json[:-3]
            clean_json = clean_json.strip()

            try:
                extracted_data = json_mod.loads(clean_json)
            except json_mod.JSONDecodeError:
                # Try to fix truncated JSON: remove trailing comma and close with }
                fixed = clean_json.rstrip().rstrip(',') + '}'
                try:
                    extracted_data = json_mod.loads(fixed)
                    logger.info(f"Fixed truncated JSON successfully")
                except json_mod.JSONDecodeError:
                    # Try regex to find any JSON-like object
                    match = re.search(r'\{[^{}]*\}', clean_json, re.DOTALL)
                    if match:
                        try:
                            extracted_data = json_mod.loads(match.group(0))
                        except json_mod.JSONDecodeError:
                            extracted_data = {}
                    else:
                        logger.warning(f"Could not parse LLM response as JSON: {clean_json[:500]}")
                        extracted_data = {}

            # Filter: only keep non-null valid keys
            valid_keys = {"name", "state", "district", "annual_income", "category", "occupation", "family_size", "age", "gender", "document_type"}
            extracted = {k: v for k, v in extracted_data.items() if k in valid_keys and v is not None}
            logger.info(f"✅ Document extracted fields: {extracted}")
        else:
            logger.warning(f"No markdown text returned from digitization. Raw keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
    except Exception as e:
        logger.warning(f"Error parsing digitized fields: {e}", exc_info=True)

    logger.info(f"Digitized document: extracted {len(extracted)} profile fields: {extracted}")
    return {"extracted_data": extracted, "raw": raw_result}


@router.post("/match", response_model=list[SchemeResponse])
async def match_schemes(
    profile: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Match government schemes based on a citizen's profile.
    Accepts a profile dict with keys like state, occupation, annual_income, category.
    """
    from jan_sahayak.services.scheme_engine import scheme_engine

    try:
        matches = await scheme_engine.find_matching_schemes(db, profile, limit=5)
        schemes = [SchemeResponse.model_validate(m["scheme"]) for m in matches if "scheme" in m]
        return schemes
    except Exception as e:
        logger.error(f"Scheme matching error: {e}", exc_info=True)
        return []


@router.get("/", response_model=SchemeListResponse)
async def list_schemes(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    category: str | None = Query(None, description="Filter by category"),
    state: str | None = Query(None, description="Filter by target state"),
    search: str | None = Query(None, description="Search by scheme name"),
    db: AsyncSession = Depends(get_db),
):
    """
    List all active government schemes with optional filtering.
    Supports pagination, category filtering, state filtering, and search.
    """
    query = select(Scheme).where(Scheme.is_active == True)  # noqa: E712

    # Apply filters
    if category:
        query = query.where(Scheme.category == category)
    if search:
        query = query.where(Scheme.name_en.ilike(f"%{search}%"))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    schemes = result.scalars().all()

    return SchemeListResponse(
        schemes=[SchemeResponse.model_validate(s) for s in schemes],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{scheme_id}", response_model=SchemeResponse)
async def get_scheme(scheme_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single scheme by its ID."""
    result = await db.execute(select(Scheme).where(Scheme.id == scheme_id))
    scheme = result.scalar_one_or_none()

    if not scheme:
        raise SchemeNotFoundError(identifier=scheme_id)

    return SchemeResponse.model_validate(scheme)


@router.post("/", response_model=SchemeResponse, status_code=201)
async def create_scheme(
    scheme_data: SchemeCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new government scheme entry."""
    scheme = Scheme(**scheme_data.model_dump())
    db.add(scheme)
    await db.flush()
    await db.refresh(scheme)
    return SchemeResponse.model_validate(scheme)


@router.get("/categories/list", response_model=list[str])
async def list_categories(db: AsyncSession = Depends(get_db)):
    """Get all unique scheme categories."""
    result = await db.execute(
        select(Scheme.category)
        .where(Scheme.is_active == True, Scheme.category.isnot(None))  # noqa: E712
        .distinct()
    )
    categories = [row[0] for row in result.all()]
    return categories


@router.post("/seed", response_model=MessageResponse)
async def seed_schemes(
    force: bool = Query(False, description="Force re-seed by deleting existing schemes"),
    db: AsyncSession = Depends(get_db),
):
    """
    Seed the database with sample government schemes.
    Only runs if the database is empty (unless force=True).
    """
    # Check if schemes already exist
    result = await db.execute(select(func.count()).select_from(Scheme))
    count = result.scalar() or 0

    if count > 0 and not force:
        return MessageResponse(message=f"Database already has {count} schemes. Use ?force=true to re-seed.")

    if count > 0 and force:
        # Delete all existing schemes for a clean re-seed
        await db.execute(Scheme.__table__.delete())
        logger.info(f"Deleted {count} existing schemes for re-seed")

    # Sample schemes data
    sample_schemes = _get_sample_schemes()

    for scheme_data in sample_schemes:
        scheme = Scheme(**scheme_data)
        db.add(scheme)

    await db.flush()
    return MessageResponse(
        message=f"Successfully seeded {len(sample_schemes)} schemes.",
        data={"count": len(sample_schemes)},
    )


def _get_sample_schemes() -> list[dict]:
    """Returns sample government scheme data for seeding."""
    return [
        {
            "name_en": "Pradhan Mantri Kisan Samman Nidhi (PM-KISAN)",
            "name_hi": "प्रधानमंत्री किसान सम्मान निधि",
            "description_en": "Income support of ₹6,000 per year to all farmer families across India, paid in three equal installments of ₹2,000 each.",
            "description_hi": "भारत भर के सभी किसान परिवारों को प्रति वर्ष ₹6,000 की आय सहायता, ₹2,000 की तीन समान किस्तों में।",
            "ministry": "Ministry of Agriculture & Farmers Welfare",
            "category": "Agriculture",
            "eligibility_criteria": {
                "occupations": ["farmer", "agriculture"],
                "max_income": 500000,
                "min_age": 18,
            },
            "benefits": "₹6,000 per year in 3 installments of ₹2,000 directly to bank account",
            "application_url": "https://pmkisan.gov.in",
            "documents_required": ["Aadhaar Card", "Bank Account Details", "Land Ownership Records"],
            "state_specific": False,
            "is_active": True,
            "source_url": "https://pmkisan.gov.in",
        },
        {
            "name_en": "Ayushman Bharat - Pradhan Mantri Jan Arogya Yojana (AB-PMJAY)",
            "name_hi": "आयुष्मान भारत - प्रधानमंत्री जन आरोग्य योजना",
            "description_en": "Health insurance coverage of ₹5 lakh per family per year for secondary and tertiary care hospitalization.",
            "description_hi": "माध्यमिक और तृतीयक देखभाल अस्पताल में भर्ती के लिए प्रति परिवार प्रति वर्ष ₹5 लाख का स्वास्थ्य बीमा कवरेज।",
            "ministry": "Ministry of Health & Family Welfare",
            "category": "Health",
            "eligibility_criteria": {
                "max_income": 500000,
                "categories": ["SC", "ST", "OBC", "General"],
            },
            "benefits": "₹5 lakh health insurance per family per year, cashless treatment at empaneled hospitals",
            "application_url": "https://pmjay.gov.in",
            "documents_required": ["Aadhaar Card", "Ration Card", "Income Certificate"],
            "state_specific": False,
            "is_active": True,
            "source_url": "https://pmjay.gov.in",
        },
        {
            "name_en": "Pradhan Mantri Awas Yojana - Gramin (PMAY-G)",
            "name_hi": "प्रधानमंत्री आवास योजना - ग्रामीण",
            "description_en": "Financial assistance for construction of pucca house with basic amenities to all eligible rural households.",
            "description_hi": "सभी पात्र ग्रामीण परिवारों को बुनियादी सुविधाओं के साथ पक्के मकान के निर्माण के लिए वित्तीय सहायता।",
            "ministry": "Ministry of Rural Development",
            "category": "Housing",
            "eligibility_criteria": {
                "max_income": 300000,
                "categories": ["SC", "ST", "OBC"],
                "min_age": 18,
            },
            "benefits": "₹1.20 lakh in plains, ₹1.30 lakh in hilly/difficult areas for house construction",
            "application_url": "https://pmayg.dord.gov.in",
            "documents_required": ["Aadhaar Card", "BPL Card", "Land Documents", "Bank Account"],
            "state_specific": False,
            "is_active": True,
            "source_url": "https://pmayg.dord.gov.in",
        },
        {
            "name_en": "Mahatma Gandhi National Rural Employment Guarantee Act (MGNREGA)",
            "name_hi": "महात्मा गांधी राष्ट्रीय ग्रामीण रोजगार गारंटी अधिनियम (मनरेगा)",
            "description_en": "Legal guarantee of 100 days of wage employment per year to every rural household whose adult members volunteer for unskilled manual work.",
            "description_hi": "हर ग्रामीण परिवार को जिसके वयस्क सदस्य अकुशल शारीरिक काम के लिए स्वेच्छा से आगे आते हैं, प्रति वर्ष 100 दिन के वेतन रोजगार की कानूनी गारंटी।",
            "ministry": "Ministry of Rural Development",
            "category": "Employment",
            "eligibility_criteria": {
                "max_income": 250000,
                "categories": ["SC", "ST", "OBC", "General"],
                "occupations": ["laborer", "labourer", "farmer", "agriculture", "unemployed", "daily wage worker"],
                "min_age": 18,
            },
            "benefits": "100 days guaranteed employment at minimum wage, unemployment allowance if work not provided",
            "application_url": "https://nrega.dord.gov.in",
            "documents_required": ["Aadhaar Card", "Job Card", "Bank Account"],
            "state_specific": False,
            "is_active": True,
            "source_url": "https://nrega.dord.gov.in",
        },
        {
            "name_en": "Pradhan Mantri Ujjwala Yojana (PMUY)",
            "name_hi": "प्रधानमंत्री उज्ज्वला योजना",
            "description_en": "Free LPG connections to women from Below Poverty Line (BPL) families to replace unclean cooking fuels.",
            "description_hi": "गरीबी रेखा से नीचे (बीपीएल) परिवारों की महिलाओं को अशुद्ध ईंधन की जगह मुफ्त एलपीजी कनेक्शन।",
            "ministry": "Ministry of Petroleum & Natural Gas",
            "category": "Energy",
            "eligibility_criteria": {
                "max_income": 200000,
                "categories": ["SC", "ST", "OBC", "General"],
                "gender": "female",
                "min_age": 18,
            },
            "benefits": "Free LPG connection, ₹1,600 assistance for gas stove and first refill",
            "application_url": "https://www.pmujjwalayojana.com",
            "documents_required": ["Aadhaar Card", "BPL Card", "Bank Account", "Passport Photo"],
            "state_specific": False,
            "is_active": True,
            "source_url": "https://www.pmujjwalayojana.com",
        },
        {
            "name_en": "Sukanya Samriddhi Yojana",
            "name_hi": "सुकन्या समृद्धि योजना",
            "description_en": "Government-backed savings scheme for girl child with high interest rate and tax benefits. Account can be opened for girls below 10 years.",
            "description_hi": "बालिकाओं के लिए उच्च ब्याज दर और कर लाभ के साथ सरकार समर्थित बचत योजना। 10 वर्ष से कम उम्र की लड़कियों के लिए खाता खोला जा सकता है।",
            "ministry": "Ministry of Finance",
            "category": "Education",
            "eligibility_criteria": {
                "gender": "female",
                "max_age": 10,
                "categories": ["SC", "ST", "OBC", "General"],
            },
            "benefits": "High interest rate (currently ~8%), tax benefits under 80C, maturity at girl's 21st birthday",
            "application_url": "https://www.nsiindia.gov.in",
            "documents_required": ["Girl's Birth Certificate", "Parent's Aadhaar", "Parent's PAN", "Address Proof"],
            "state_specific": False,
            "is_active": True,
            "source_url": "https://www.nsiindia.gov.in",
        },
        {
            "name_en": "PM Vishwakarma Yojana",
            "name_hi": "पीएम विश्वकर्मा योजना",
            "description_en": "Support for traditional artisans and craftspeople with skill training, modern tools, credit support up to ₹3 lakh, and digital payment integration.",
            "description_hi": "पारंपरिक कारीगरों और शिल्पकारों को कौशल प्रशिक्षण, आधुनिक उपकरण, ₹3 लाख तक की ऋण सहायता और डिजिटल भुगतान एकीकरण।",
            "ministry": "Ministry of Micro, Small & Medium Enterprises",
            "category": "Skill Development",
            "eligibility_criteria": {
                "occupations": [
                    "carpenter", "blacksmith", "goldsmith", "potter", "sculptor",
                    "cobbler", "tailor", "weaver", "mason", "barber",
                    "washerman", "artisan", "craftsman",
                ],
                "categories": ["SC", "ST", "OBC", "General"],
                "min_age": 18,
            },
            "benefits": "₹15,000 toolkit, up to ₹3 lakh collateral-free credit at 5% interest, skill training with ₹500/day stipend",
            "application_url": "https://pmvishwakarma.gov.in",
            "documents_required": [
                "Aadhaar Card", "Bank Account", "Mobile Number",
                "Skill verification by Gram Panchayat",
            ],
            "state_specific": False,
            "is_active": True,
            "source_url": "https://pmvishwakarma.gov.in",
        },
        {
            "name_en": "Kisan Credit Card (KCC)",
            "name_hi": "किसान क्रेडिट कार्ड",
            "description_en": "Short-term credit support to farmers for crop production, post-harvest needs, and farm maintenance at low interest rates.",
            "description_hi": "किसानों को फसल उत्पादन, कटाई के बाद की जरूरतों और कृषि रखरखाव के लिए कम ब्याज दरों पर अल्पकालिक ऋण सहायता।",
            "ministry": "Ministry of Agriculture & Farmers Welfare",
            "category": "Agriculture",
            "eligibility_criteria": {
                "occupations": ["farmer", "agriculture", "fisherman", "animal husbandry"],
                "min_age": 18,
                "max_age": 75,
            },
            "benefits": "Credit up to ₹3 lakh at 4% interest (with subvention), crop insurance coverage, flexible repayment",
            "application_url": "https://pmkisan.gov.in",
            "documents_required": ["Aadhaar Card", "Land Records", "Bank Account", "Passport Photo"],
            "state_specific": False,
            "is_active": True,
            "source_url": "https://pmkisan.gov.in",
        },
        {
            "name_en": "Ladli Behna Yojana",
            "name_hi": "लाडली बहना योजना",
            "description_en": "Monthly financial assistance of ₹1,250 to eligible women in Madhya Pradesh to promote their economic independence.",
            "description_hi": "मध्य प्रदेश में पात्र महिलाओं को उनकी आर्थिक स्वतंत्रता को बढ़ावा देने के लिए ₹1,250 की मासिक वित्तीय सहायता।",
            "ministry": "Women & Child Development Department, MP",
            "category": "Women Welfare",
            "eligibility_criteria": {
                "max_income": 250000,
                "categories": ["SC", "ST", "OBC", "General"],
                "gender": "female",
                "min_age": 21,
                "max_age": 60,
            },
            "benefits": "₹1,250 per month directly to women's bank account",
            "application_url": "https://cmladlibahna.mp.gov.in",
            "documents_required": ["Aadhaar Card", "Samagra ID", "Bank Account"],
            "state_specific": True,
            "target_states": ["Madhya Pradesh"],
            "is_active": True,
            "source_url": "https://cmladlibahna.mp.gov.in",
        },
        {
            "name_en": "PM Surya Ghar Muft Bijli Yojana",
            "name_hi": "पीएम सूर्य घर मुफ्त बिजली योजना",
            "description_en": "Subsidy for installing rooftop solar panels on residential houses, providing up to 300 units of free electricity per month.",
            "description_hi": "आवासीय मकानों पर छत पर सौर पैनल लगाने के लिए सब्सिडी, प्रति माह 300 यूनिट तक मुफ्त बिजली प्रदान करती है।",
            "ministry": "Ministry of New & Renewable Energy",
            "category": "Energy",
            "eligibility_criteria": {
                "categories": ["SC", "ST", "OBC", "General"],
                "min_age": 18,
            },
            "benefits": "Up to ₹78,000 subsidy for rooftop solar, 300 units free electricity per month",
            "application_url": "https://pmsuryaghar.gov.in",
            "documents_required": ["Aadhaar Card", "Electricity Bill", "Bank Account", "Property Documents"],
            "state_specific": False,
            "is_active": True,
            "source_url": "https://pmsuryaghar.gov.in",
        },
    ]


@router.get("/{scheme_id}/explain")
@limiter.limit("30/minute")
async def explain_scheme_endpoint(
    request: Request,
    scheme_id: str,
    language: str = Query("hindi", description="Language of explanation"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Explain a welfare scheme in simple terms using Sarvam AI."""
    result = await db.execute(select(Scheme).where(Scheme.id == scheme_id))
    scheme = result.scalar_one_or_none()
    if not scheme:
        raise SchemeNotFoundError(identifier=scheme_id)

    explanation = await scheme_engine.explain_scheme(scheme, language=language)
    return {"scheme_id": scheme_id, "language": language, "explanation": explanation}


@router.post("/{scheme_id}/guide")
@limiter.limit("20/minute")
async def generate_guide_endpoint(
    request: Request,
    scheme_id: str,
    profile_data: dict,
    language: str = Query("hindi", description="Language of guide"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a step-by-step personalized application guide for a scheme."""
    result = await db.execute(select(Scheme).where(Scheme.id == scheme_id))
    scheme = result.scalar_one_or_none()
    if not scheme:
        raise SchemeNotFoundError(identifier=scheme_id)

    guide = await scheme_engine.generate_application_guide(scheme, profile_data, language=language)
    return {"scheme_id": scheme_id, "language": language, "guide": guide}

