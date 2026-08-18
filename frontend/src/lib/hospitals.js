/** Display names. Full names are long; charts need something readable. */
const SHORT = {
  'Alice Ho Miu Ling Nethersole Hospital': 'Alice Ho Nethersole',
  'Caritas Medical Centre': 'Caritas',
  'Kwong Wah Hospital': 'Kwong Wah',
  'North District Hospital': 'North District',
  'North Lantau Hospital': 'North Lantau',
  'Pamela Youde Nethersole Eastern Hospital': 'Pamela Youde Eastern',
  'Pok Oi Hospital': 'Pok Oi',
  'Prince of Wales Hospital': 'Prince of Wales',
  'Princess Margaret Hospital': 'Princess Margaret',
  'Queen Elizabeth Hospital': 'Queen Elizabeth',
  'Queen Mary Hospital': 'Queen Mary',
  'Ruttonjee Hospital': 'Ruttonjee',
  'St John Hospital': 'St John',
  'Tin Shui Wai Hospital': 'Tin Shui Wai',
  'Tseung Kwan O Hospital': 'Tseung Kwan O',
  'Tuen Mun Hospital': 'Tuen Mun',
  'United Christian Hospital': 'United Christian',
  'Yan Chai Hospital': 'Yan Chai',
}

export function shortName(full) {
  if (!full) return ''
  if (SHORT[full]) return SHORT[full]
  return full.replace(/\s+(Hospital|Medical Centre)$/i, '')
}

/**
 * Starting points offered when the browser will not share a location
 * (permission denied, insecure context, or the user simply prefers not to).
 * Coarse district centroids, good enough to rank hospitals by travel time.
 */
export const DISTRICTS = [
  { id: 'central', name: 'Central & Sheung Wan', lat: 22.2847, lon: 114.1548 },
  { id: 'causeway', name: 'Causeway Bay & Wan Chai', lat: 22.2793, lon: 114.1828 },
  { id: 'north-point', name: 'North Point & Quarry Bay', lat: 22.2870, lon: 114.2000 },
  { id: 'aberdeen', name: 'Aberdeen & Southern', lat: 22.2480, lon: 114.1550 },
  { id: 'tst', name: 'Tsim Sha Tsui & Jordan', lat: 22.2988, lon: 114.1722 },
  { id: 'mongkok', name: 'Mong Kok & Yau Ma Tei', lat: 22.3193, lon: 114.1694 },
  { id: 'kowloon-city', name: 'Kowloon City & Ho Man Tin', lat: 22.3282, lon: 114.1913 },
  { id: 'kwun-tong', name: 'Kwun Tong & Ngau Tau Kok', lat: 22.3130, lon: 114.2260 },
  { id: 'sham-shui-po', name: 'Sham Shui Po & Cheung Sha Wan', lat: 22.3303, lon: 114.1628 },
  { id: 'kwai-tsing', name: 'Kwai Chung & Tsing Yi', lat: 22.3570, lon: 114.1300 },
  { id: 'tsuen-wan', name: 'Tsuen Wan', lat: 22.3710, lon: 114.1140 },
  { id: 'sha-tin', name: 'Sha Tin & Ma On Shan', lat: 22.3820, lon: 114.1880 },
  { id: 'tai-po', name: 'Tai Po', lat: 22.4500, lon: 114.1640 },
  { id: 'fanling', name: 'Fanling & Sheung Shui', lat: 22.4960, lon: 114.1380 },
  { id: 'tseung-kwan-o', name: 'Tseung Kwan O', lat: 22.3080, lon: 114.2600 },
  { id: 'tuen-mun', name: 'Tuen Mun', lat: 22.3910, lon: 113.9770 },
  { id: 'yuen-long', name: 'Yuen Long & Tin Shui Wai', lat: 22.4450, lon: 114.0220 },
  { id: 'lantau', name: 'Tung Chung & Lantau', lat: 22.2890, lon: 113.9420 },
]

/** Great-circle distance in km. Only used as a fallback when the API omits it. */
export function haversineKm(a, b) {
  if (!a || !b) return null
  const R = 6371
  const toRad = (d) => (d * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLon = toRad(b.lon - a.lon)
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2
  return Math.round(2 * R * Math.asin(Math.sqrt(s)) * 10) / 10
}

/**
 * Access facts that are true of a hospital no matter what was asked.
 *
 * The server sends a travel refusal (`reason`) for St John only when a journey
 * was actually costed, that is, only when the reader supplied a starting point.
 * With no origin the field is null, and St John was then ranked second on
 * queue length alone, reading as an ordinary "0 – 16 min" option with nothing
 * anywhere on the page to say it is on an island with no road to it.
 *
 * This is a geographic fact, not a modelled quantity: Cheung Chau is car-free
 * and has no road link, so the only way in is a scheduled ferry. The wording is
 * the server's own, kept short enough to sit on a card. When the server does
 * send a reason, the server's text wins.
 */
const ACCESS_NOTES = {
  'St John Hospital':
    'St John Hospital is on Cheung Chau, a car-free island with no road link to the rest of Hong Kong. Reaching it means a scheduled ferry from Central, so no honest travel time can be produced for it. If you are already on Cheung Chau, this is your local A&E and the walk is short.',
}

export function accessNote(hospital) {
  return ACCESS_NOTES[hospital] || null
}
