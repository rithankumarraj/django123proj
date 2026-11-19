"""
India Post PIN Code Directory Service
Data source: India Post (Department of Posts, Ministry of Communications, Government of India)
Published via data.gov.in and postalpincode.in open directory API.
"""

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Complete official directory mapping of Indian States and Union Territories with all their Districts
INDIA_STATES_DISTRICTS: Dict[str, List[str]] = {
    "Andaman and Nicobar Islands": [
        "Nicobar", "North and Middle Andaman", "South Andaman"
    ],
    "Andhra Pradesh": [
        "Alluri Sitharama Raju", "Anakapalli", "Ananthapuramu", "Annamayya", "Bapatla",
        "Chittoor", "Dr. B.R. Ambedkar Konaseema", "East Godavari", "Eluru", "Guntur",
        "Kakinada", "Krishna", "Kurnool", "Nandyal", "NTR", "Palnadu",
        "Parvathipuram Manyam", "Prakasam", "Sri Potti Sriramulu Nellore", "Sri Sathya Sai",
        "Srikakulam", "Tirupati", "Visakhapatnam", "Vizianagaram", "West Godavari", "YSR Kadapa"
    ],
    "Arunachal Pradesh": [
        "Anjaw", "Changlang", "Dibang Valley", "East Kameng", "East Siang", "Itanagar",
        "Kamle", "Kra Daadi", "Kurung Kumey", "Leparada", "Lohit", "Longding",
        "Lower Dibang Valley", "Lower Siang", "Lower Subansiri", "Namsai", "Pakke Kessang",
        "Papum Pare", "Shi Yomi", "Siang", "Tawang", "Tirap", "Upper Siang", "Upper Subansiri",
        "West Kameng", "West Siang"
    ],
    "Assam": [
        "Baksa", "Barpeta", "Biswanath", "Bongaigaon", "Cachar", "Charaideo", "Chirang",
        "Darrang", "Dhemaji", "Dhubri", "Dibrugarh", "Dima Hasao", "Goalpara", "Golaghat",
        "Hailakandi", "Hojai", "Jorhat", "Kamrup", "Kamrup Metropolitan", "Karbi Anglong",
        "Karimganj", "Kokrajhar", "Lakhimpur", "Majuli", "Morigaon", "Nagaon", "Nalbari",
        "Sivasagar", "Sonitpur", "South Salmara-Mankachar", "Tinsukia", "Udalguri", "West Karbi Anglong"
    ],
    "Bihar": [
        "Araria", "Arwal", "Aurangabad", "Banka", "Begusarai", "Bhagalpur", "Bhojpur",
        "Buxar", "Darbhanga", "East Champaran", "Gaya", "Gopalganj", "Jamui", "Jehanabad",
        "Kaimur", "Katihar", "Khagaria", "Kishanganj", "Lakhisarai", "Madhepura",
        "Madhubani", "Munger", "Muzaffarpur", "Nalanda", "Nawada", "Patna", "Purnia",
        "Rohtas", "Saharsa", "Samastipur", "Saran", "Sheikhpura", "Sheohar", "Sitamarhi",
        "Siwan", "Supaul", "Vaishali", "West Champaran"
    ],
    "Chandigarh": [
        "Chandigarh"
    ],
    "Chhattisgarh": [
        "Balod", "Baloda Bazar", "Balrampur", "Bastar", "Bemetara", "Bijapur", "Bilaspur",
        "Dantewada", "Dhamtari", "Durg", "Gariaband", "Gaurela-Pendra-Marwahi", "Janjgir-Champa",
        "Jashpur", "Kabirdham", "Kanker", "Khairagarh", "Kondagaon", "Korba", "Koriya",
        "Mahasamund", "Manendragarh-Chirmiri-Bharatpur", "Mohla-Manpur-Ambagarh Chowki",
        "Mungeli", "Narayanpur", "Raigarh", "Raipur", "Rajnandgaon", "Sakti", "Sarangarh-Bilaigarh",
        "Sukma", "Surajpur", "Surguja"
    ],
    "Dadra and Nagar Haveli and Daman and Diu": [
        "Dadra and Nagar Haveli", "Daman", "Diu"
    ],
    "Delhi": [
        "Central Delhi", "East Delhi", "New Delhi", "North Delhi", "North East Delhi",
        "North West Delhi", "Shahdara", "South Delhi", "South East Delhi", "South West Delhi", "West Delhi"
    ],
    "Goa": [
        "North Goa", "South Goa"
    ],
    "Gujarat": [
        "Ahmedabad", "Amreli", "Anand", "Aravalli", "Banaskantha", "Bharuch", "Bhavnagar",
        "Botad", "Chhota Udaipur", "Dahod", "Dang", "Devbhoomi Dwarka", "Gandhinagar",
        "Gir Somnath", "Jamnagar", "Junagadh", "Kheda", "Kutch", "Mahisagar", "Mehsana",
        "Morbi", "Narmada", "Navsari", "Panchmahal", "Patan", "Porbandar", "Rajkot",
        "Sabarkantha", "Surat", "Surendranagar", "Tapi", "Vadodara", "Valsad"
    ],
    "Haryana": [
        "Ambala", "Bhiwani", "Charkhi Dadri", "Faridabad", "Fatehabad", "Gurugram",
        "Hisar", "Jhajjar", "Jind", "Kaithal", "Karnal", "Kurukshetra", "Mahendragarh",
        "Nuh", "Palwal", "Panchkula", "Panipat", "Rewari", "Rohtak", "Sirsa", "Sonipat", "Yamunanagar"
    ],
    "Himachal Pradesh": [
        "Bilaspur", "Chamba", "Hamirpur", "Kangra", "Kinnaur", "Kullu", "Lahaul and Spiti",
        "Mandi", "Shimla", "Sirmaur", "Solan", "Una"
    ],
    "Jammu and Kashmir": [
        "Anantnag", "Bandipora", "Baramulla", "Budgam", "Doda", "Ganderbal", "Jammu",
        "Kathua", "Kishtwar", "Kulgam", "Kupwara", "Poonch", "Pulwama", "Rajouri",
        "Ramban", "Reasi", "Samba", "Shopian", "Srinagar", "Udhampur"
    ],
    "Jharkhand": [
        "Bokaro", "Chatra", "Deoghar", "Dhanbad", "Dumka", "East Singhbhum", "Garhwa",
        "Giridih", "Godda", "Gumla", "Hazaribagh", "Jamtara", "Khunti", "Koderma",
        "Latehar", "Lohardaga", "Pakur", "Palamu", "Ramgarh", "Ranchi", "Sahebganj",
        "Seraikela Kharsawan", "Simdega", "West Singhbhum"
    ],
    "Karnataka": [
        "Bagalkote", "Ballari", "Belagavi", "Bengaluru Rural", "Bengaluru Urban", "Bidar",
        "Chamarajanagara", "Chikkaballapura", "Chikkamagaluru", "Chitradurga", "Dakshina Kannada",
        "Davanagere", "Dharwad", "Gadag", "Hassan", "Haveri", "Kalaburagi", "Kodagu",
        "Kolar", "Koppal", "Mandya", "Mysuru", "Raichur", "Ramanagara", "Shivamogga",
        "Tumakuru", "Udupi", "Uttara Kannada", "Vijayanagara", "Vijayapura", "Yadgir"
    ],
    "Kerala": [
        "Alappuzha", "Ernakulam", "Idukki", "Kannur", "Kasaragod", "Kollam", "Kottayam",
        "Kozhikode", "Malappuram", "Palakkad", "Pathanamthitta", "Thiruvananthapuram",
        "Thrissur", "Wayanad"
    ],
    "Ladakh": [
        "Kargil", "Leh"
    ],
    "Lakshadweep": [
        "Lakshadweep"
    ],
    "Madhya Pradesh": [
        "Agar Malwa", "Alirajpur", "Anuppur", "Ashoknagar", "Balaghat", "Barwani",
        "Betul", "Bhind", "Bhopal", "Burhanpur", "Chhatarpur", "Chhindwara", "Damoh",
        "Datia", "Dewas", "Dhar", "Dindori", "Guna", "Gwalior", "Harda", "Hoshangabad",
        "Indore", "Jabalpur", "Jhabua", "Katni", "Khandwa", "Khargone", "Mandla",
        "Mandsaur", "Morena", "Narsinghpur", "Neemuch", "Niwari", "Panna", "Raisen",
        "Rajgarh", "Ratlam", "Rewa", "Sagar", "Satna", "Sehore", "Seoni", "Shahdol",
        "Shajapur", "Sheopur", "Shivpuri", "Sidhi", "Singrauli", "Tikamgarh", "Ujjain",
        "Umaria", "Vidisha"
    ],
    "Maharashtra": [
        "Ahmednagar", "Akola", "Amravati", "Aurangabad", "Beed", "Bhandara", "Buldhana",
        "Chandrapur", "Dhule", "Gadchiroli", "Gondia", "Hingoli", "Jalgaon", "Jalna",
        "Kolhapur", "Latur", "Mumbai City", "Mumbai Suburban", "Nagpur", "Nanded",
        "Nandurbar", "Nashik", "Osmanabad", "Palghar", "Parbhani", "Pune", "Raigad",
        "Ratnagiri", "Sangli", "Satara", "Sindhudurg", "Solapur", "Thane", "Wardha",
        "Washim", "Yavatmal"
    ],
    "Manipur": [
        "Bishnupur", "Chandel", "Churachandpur", "Imphal East", "Imphal West", "Jiribam",
        "Kakching", "Kamjong", "Kangpokpi", "Noney", "Pherzawl", "Senapati", "Tamenglong",
        "Tengnoupal", "Thoubal", "Ukhrul"
    ],
    "Meghalaya": [
        "Eastern West Khasi Hills", "East Garo Hills", "East Jaintia Hills", "East Khasi Hills",
        "North Garo Hills", "Ri Bhoi", "South Garo Hills", "South West Garo Hills",
        "South West Khasi Hills", "West Garo Hills", "West Jaintia Hills", "West Khasi Hills"
    ],
    "Mizoram": [
        "Aizawl", "Champhai", "Hnahthial", "Khawzawl", "Kolasib", "Lawngtlai",
        "Lunglei", "Mamit", "Saiha", "Saitual", "Serchhip"
    ],
    "Nagaland": [
        "Chümoukedima", "Dimapur", "Kiphire", "Kohima", "Longleng", "Mokokchung",
        "Mon", "Niuland", "Noklak", "Peren", "Phek", "Shamator", "Tseminyü",
        "Tuensang", "Wokha", "Zunheboto"
    ],
    "Odisha": [
        "Angul", "Balangir", "Balasore", "Bargarh", "Bhadrak", "Boudh", "Cuttack",
        "Deogarh", "Dhenkanal", "Gajapati", "Ganjam", "Jagatsinghpur", "Jajpur",
        "Jharsuguda", "Kalahandi", "Kandhamal", "Kendrapara", "Kendujhar", "Khordha",
        "Koraput", "Malkangiri", "Mayurbhanj", "Nabarangpur", "Nayagarh", "Nuapada",
        "Puri", "Rayagada", "Sambalpur", "Subarnapur", "Sundargarh"
    ],
    "Puducherry": [
        "Karaikal", "Mahe", "Puducherry", "Yanam"
    ],
    "Punjab": [
        "Amritsar", "Barnala", "Bathinda", "Faridkot", "Fatehgarh Sahib", "Fazilka",
        "Ferozepur", "Gurdaspur", "Hoshiarpur", "Jalandhar", "Kapurthala", "Ludhiana",
        "Malerkotla", "Mansa", "Moga", "Muktsar", "Pathankot", "Patiala", "Rupnagar",
        "Sahibzada Ajit Singh Nagar", "Sangrur", "Shahid Bhagat Singh Nagar", "Sri Muktsar Sahib", "Tarn Taran"
    ],
    "Rajasthan": [
        "Ajmer", "Alwar", "Anupgarh", "Balotra", "Banswara", "Baran", "Barmer", "Beawar",
        "Bharatpur", "Bhilwara", "Bikaner", "Bundi", "Chittorgarh", "Churu", "Dausa",
        "Deeg", "Dholpur", "Didwana-Kuchaman", "Dudu", "Dungarpur", "Gangapur City",
        "Hanumangarh", "Jaipur", "Jaipur Rural", "Jaisalmer", "Jalore", "Jhalawar",
        "Jhunjhunu", "Jodhpur", "Jodhpur Rural", "Karauli", "Kekri", "Khairthal-Tijara",
        "Kota", "Kotputli-Behror", "Nagaur", "Neem Ka Thana", "Pali", "Phalodi",
        "Pratapgarh", "Rajsamand", "Salumbar", "Sanchore", "Sawai Madhopur", "Shahpura",
        "Sikar", "Sirohi", "Sri Ganganagar", "Tonk", "Udaipur"
    ],
    "Sikkim": [
        "Gangtok", "Gyalshing", "Mangan", "Namchi", "Pakyong", "Soreng"
    ],
    "Tamil Nadu": [
        "Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore", "Dharmapuri",
        "Dindigul", "Erode", "Kallakurichi", "Kanchipuram", "Kanyakumari", "Karur",
        "Krishnagiri", "Madurai", "Mayiladuthurai", "Nagapattinam", "Namakkal", "Nilgiris",
        "Perambalur", "Pudukkottai", "Ramanathapuram", "Ranipet", "Salem", "Sivaganga",
        "Tenkasi", "Thanjavur", "Theni", "Thoothukudi", "Tiruchirappalli", "Tirunelveli",
        "Tirupathur", "Tiruppur", "Tiruvallur", "Tiruvannamalai", "Tiruvarur", "Vellore",
        "Viluppuram", "Virudhunagar"
    ],
    "Telangana": [
        "Adilabad", "Bhadradri Kothagudem", "Hanumakonda", "Hyderabad", "Jagtial",
        "Jangaon", "Jayashankar Bhupalpally", "Jogulamba Gadwal", "Kamareddy", "Karimnagar",
        "Khammam", "Kumuram Bheem Asifabad", "Mahabubabad", "Mahabubnagar", "Mancherial",
        "Medak", "Medchal-Malkajgiri", "Mulugu", "Nagarkurnool", "Nalgonda", "Narayanpet",
        "Nirmal", "Nizamabad", "Peddapalli", "Rajanna Sircilla", "Ranga Reddy", "Sangareddy",
        "Siddipet", "Suryapet", "Vikarabad", "Wanaparthy", "Warangal", "Yadadri Bhuvanagiri"
    ],
    "Tripura": [
        "Dhalai", "Gomati", "Khowai", "North Tripura", "Sepahijala", "South Tripura",
        "Unakoti", "West Tripura"
    ],
    "Uttar Pradesh": [
        "Agra", "Aligarh", "Ambedkar Nagar", "Amethi", "Amroha", "Auraiya", "Ayodhya",
        "Azamgarh", "Badaun", "Baghpat", "Bahraich", "Ballia", "Balrampur", "Banda",
        "Barabanki", "Bareilly", "Basti", "Bhadohi", "Bijnor", "Bulandshahr", "Chandauli",
        "Chitrakoot", "Deoria", "Etah", "Etawah", "Farrukhabad", "Fatehpur", "Firozabad",
        "Gautam Buddha Nagar", "Ghaziabad", "Ghazipur", "Gonda", "Gorakhpur", "Hamirpur",
        "Hapur", "Hardoi", "Hathras", "Jalaun", "Jaunpur", "Jhansi", "Kannauj",
        "Kanpur Dehat", "Kanpur Nagar", "Kasganj", "Kaushambi", "Kheri", "Kushinagar",
        "Lalitpur", "Lucknow", "Maharajganj", "Mahoba", "Mainpuri", "Mathura", "Mau",
        "Meerut", "Mirzapur", "Moradabad", "Muzaffarnagar", "Pilibhit", "Pratapgarh",
        "Prayagraj", "Raebareli", "Rampur", "Saharanpur", "Sambhal", "Sant Kabir Nagar",
        "Shahjahanpur", "Shamli", "Shrawasti", "Siddharthnagar", "Sitapur", "Sonbhadra",
        "Sultanpur", "Unnao", "Varanasi"
    ],
    "Uttarakhand": [
        "Almora", "Bageshwar", "Chamoli", "Champawat", "Dehradun", "Haridwar",
        "Nainital", "Pauri Garhwal", "Pithoragarh", "Rudraprayag", "Tehri Garhwal",
        "Udham Singh Nagar", "Uttarkashi"
    ],
    "West Bengal": [
        "Alipurduar", "Bankura", "Birbhum", "Cooch Behar", "Dakshin Dinajpur", "Darjeeling",
        "Hooghly", "Howrah", "Jalpaiguri", "Jhargram", "Kalimpong", "Kolkata", "Malda",
        "Murshidabad", "Nadia", "North 24 Parganas", "Paschim Bardhaman", "Paschim Medinipur",
        "Purba Bardhaman", "Purba Medinipur", "Purulia", "South 24 Parganas", "Uttar Dinajpur"
    ],
}

# In-memory LRU-like caches to avoid repeated outbound calls
_PINCODE_CACHE: Dict[str, Dict[str, Any]] = {}
_DISTRICT_CACHE: Dict[str, Dict[str, Any]] = {}


def get_states_and_districts() -> Dict[str, List[str]]:
    """Return all Indian States and their Districts."""
    return INDIA_STATES_DISTRICTS


def lookup_pincode(pincode: str) -> Dict[str, Any]:
    """
    Lookup a 6-digit PIN code against the India Post directory.
    Returns:
        {
            "valid": True/False,
            "pincode": "625001",
            "district": "Madurai",
            "state": "Tamil Nadu",
            "post_offices": [ ... ],
            "source": "India Post Directory (data.gov.in)"
        }
    """
    clean_pin = re.sub(r"\D", "", str(pincode).strip())
    if len(clean_pin) != 6:
        return {
            "valid": False,
            "pincode": clean_pin,
            "error": "A valid Indian postal PIN code must be exactly 6 digits.",
        }

    # Check cache
    if clean_pin in _PINCODE_CACHE:
        return _PINCODE_CACHE[clean_pin]

    url = f"https://api.postalpincode.in/pincode/{clean_pin}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "JCSD-IndiaPostDirectory/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=4.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                item = data[0]
                status = item.get("Status")
                post_offices_raw = item.get("PostOffice") or []
                if status == "Success" and post_offices_raw:
                    first = post_offices_raw[0]
                    district = first.get("District", "").strip()
                    state = first.get("State", "").strip()

                    po_list = []
                    for po in post_offices_raw:
                        po_list.append({
                            "name": po.get("Name", ""),
                            "branch_type": po.get("BranchType", ""),
                            "delivery_status": po.get("DeliveryStatus", ""),
                            "circle": po.get("Circle", ""),
                            "district": po.get("District", ""),
                            "state": po.get("State", ""),
                        })

                    result = {
                        "valid": True,
                        "pincode": clean_pin,
                        "district": district,
                        "state": state,
                        "post_offices": po_list,
                        "source": "India Post Directory (data.gov.in)",
                    }
                    _PINCODE_CACHE[clean_pin] = result
                    return result

        # If not found or empty
        err_res = {
            "valid": False,
            "pincode": clean_pin,
            "error": f"PIN code '{clean_pin}' was not found in India Post directory.",
        }
        _PINCODE_CACHE[clean_pin] = err_res
        return err_res

    except Exception as exc:
        logger.warning("India Post directory API request failed for PIN %s: %s", clean_pin, exc)
        # Attempt fallback heuristic based on first 2 digits
        fallback_state = _guess_state_by_pin_prefix(clean_pin)
        fallback_res = {
            "valid": True,
            "pincode": clean_pin,
            "district": "",
            "state": fallback_state or "",
            "post_offices": [],
            "source": "India Post Postal Circle Heuristic",
            "is_fallback": True,
        }
        return fallback_res


def get_district_pincodes(district: str, state: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch all serviceable PIN codes under a specific District from the India Post directory.
    """
    dist_clean = district.strip()
    cache_key = f"{state or ''}:{dist_clean}".lower()
    if cache_key in _DISTRICT_CACHE:
        return _DISTRICT_CACHE[cache_key]

    quoted = urllib.parse.quote(dist_clean)
    url = f"https://api.postalpincode.in/postoffice/{quoted}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "JCSD-IndiaPostDirectory/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                item = data[0]
                status = item.get("Status")
                post_offices_raw = item.get("PostOffice") or []
                if status == "Success" and post_offices_raw:
                    matched_pos = []
                    pins_set = set()
                    ret_state = state or ""

                    for po in post_offices_raw:
                        po_state = po.get("State", "").strip()
                        po_dist = po.get("District", "").strip()
                        pin = po.get("Pincode", "").strip()

                        # If state is specified, filter matching state (case-insensitive substring)
                        if state and po_state and state.lower() not in po_state.lower() and po_state.lower() not in state.lower():
                            continue

                        if not ret_state and po_state:
                            ret_state = po_state

                        if pin and len(pin) == 6:
                            pins_set.add(pin)
                            matched_pos.append({
                                "name": po.get("Name", ""),
                                "pincode": pin,
                                "branch_type": po.get("BranchType", ""),
                                "delivery_status": po.get("DeliveryStatus", ""),
                                "district": po_dist,
                                "state": po_state,
                            })

                    sorted_pins = sorted(list(pins_set))
                    result = {
                        "success": True,
                        "district": dist_clean,
                        "state": ret_state,
                        "count": len(sorted_pins),
                        "pincodes": sorted_pins,
                        "post_offices": matched_pos,
                        "source": "India Post Directory (data.gov.in)",
                    }
                    _DISTRICT_CACHE[cache_key] = result
                    return result

        err_res = {
            "success": False,
            "district": dist_clean,
            "state": state or "",
            "count": 0,
            "pincodes": [],
            "error": f"No post offices found for district '{dist_clean}'.",
        }
        return err_res

    except Exception as exc:
        logger.warning("Failed to fetch district PINs for '%s': %s", dist_clean, exc)
        return {
            "success": False,
            "district": dist_clean,
            "state": state or "",
            "count": 0,
            "pincodes": [],
            "error": f"Unable to reach India Post directory: {str(exc)}",
        }


def verify_address_pincode(pincode: str, city: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
    """
    Verify customer-entered address details (city and state) against India Post directory.
    Checks:
    1. Is the PIN code valid in India?
    2. Does the entered State match the official State?
    3. Does the entered City/District match or lie within this PIN code area?
    """
    lookup = lookup_pincode(pincode)
    if not lookup.get("valid"):
        return {
            "is_valid": False,
            "error": lookup.get("error", "Invalid PIN code"),
            "matches_state": False,
            "matches_city": False,
            "suggested_district": "",
            "suggested_state": "",
            "message": f"PIN code {pincode} was not found in India Post directory.",
        }

    official_dist = lookup.get("district", "").strip()
    official_state = lookup.get("state", "").strip()
    po_names = [po.get("name", "").strip().lower() for po in lookup.get("post_offices", [])]

    state_match = True
    if state and official_state:
        st_clean = state.strip().lower()
        off_st_clean = official_state.lower()
        state_match = (st_clean == off_st_clean) or (st_clean in off_st_clean) or (off_st_clean in st_clean)

    city_match = True
    if city and official_dist:
        ct_clean = city.strip().lower()
        off_dist_clean = official_dist.lower()
        city_match = (
            (ct_clean == off_dist_clean)
            or (ct_clean in off_dist_clean)
            or (off_dist_clean in ct_clean)
            or any(ct_clean in pon or pon in ct_clean for pon in po_names)
        )

    return {
        "is_valid": True,
        "pincode": lookup.get("pincode"),
        "matches_state": state_match,
        "matches_city": city_match,
        "suggested_district": official_dist,
        "suggested_state": official_state,
        "post_offices": lookup.get("post_offices", []),
        "source": lookup.get("source", "India Post Directory (data.gov.in)"),
        "message": f"Verified by India Post: {official_dist}, {official_state}" if (state_match and city_match) else f"India Post directory indicates: {official_dist}, {official_state}",
    }


def _guess_state_by_pin_prefix(pin: str) -> Optional[str]:
    """Fallback circle mapping based on PIN code prefix."""
    if len(pin) < 2:
        return None
    p2 = pin[:2]
    if p2 == "11":
        return "Delhi"
    elif p2 in ("12", "13"):
        return "Haryana"
    elif p2 in ("14", "15"):
        return "Punjab"
    elif p2 == "16":
        return "Chandigarh"
    elif p2 == "17":
        return "Himachal Pradesh"
    elif p2 in ("18", "19"):
        return "Jammu and Kashmir"
    elif p2 in ("20", "21", "22", "23", "24", "25", "26", "27", "28"):
        return "Uttar Pradesh"
    elif p2 in ("30", "31", "32", "33", "34"):
        return "Rajasthan"
    elif p2 in ("36", "37", "38", "39"):
        return "Gujarat"
    elif p2 in ("40", "41", "42", "43", "44"):
        return "Maharashtra"
    elif p2 in ("45", "46", "47", "48", "49"):
        return "Madhya Pradesh"
    elif p2 in ("50", "51", "52", "53"):
        return "Andhra Pradesh"
    elif p2 in ("56", "57", "58", "59"):
        return "Karnataka"
    elif p2 in ("60", "61", "62", "63", "64"):
        return "Tamil Nadu"
    elif p2 in ("67", "68", "69"):
        return "Kerala"
    elif p2 in ("70", "71", "72", "73", "74"):
        return "West Bengal"
    elif p2 in ("75", "76", "77"):
        return "Odisha"
    elif p2 == "78":
        return "Assam"
    elif p2 in ("80", "81", "82", "83", "84", "85"):
        return "Bihar"
    return None
