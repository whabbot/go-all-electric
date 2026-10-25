import { useSession } from '../context/SessionContext'
import type { KnownHouse } from '../api'

export function HouseDetails() {
  const { houseDetails, setHouseDetails } = useSession()
  const area = houseDetails.floor_area_m2
  const invalidArea = area != null && (!Number.isFinite(area) || area < 10 || area > 1000)

  return (
    <details className="known-details card">
      <summary>Add details you know</summary>
      <div className="known-details-body">
        <p className="subtle">
          Optional. Your entries override the EPC house geometry. Confirm at survey.
          Flats, maisonettes and park homes use the bill estimate only.
        </p>
        <div className="known-field">
          <label htmlFor="house-type">House type{houseDetails.house_type && ' (you)'}</label>
          <select
            id="house-type"
            value={houseDetails.house_type ?? ''}
            onChange={e => setHouseDetails({
              ...houseDetails,
              house_type: (e.target.value || undefined) as KnownHouse['house_type'],
            })}
          >
            <option value="">Use EPC / not sure</option>
            <option value="detached">Detached</option>
            <option value="semi_detached">Semi-detached</option>
            <option value="end_terrace">End-terrace</option>
            <option value="mid_terrace">Mid-terrace</option>
            <option value="bungalow">Bungalow</option>
          </select>
        </div>
        <div className="known-field">
          <label htmlFor="house-area">Floor area (m²){area != null && ' (you)'}</label>
          <input
            id="house-area"
            type="number"
            min="10"
            max="1000"
            step="any"
            value={area ?? ''}
            aria-invalid={invalidArea || undefined}
            aria-describedby={invalidArea ? 'house-area-error' : undefined}
            onChange={e => setHouseDetails({
              ...houseDetails,
              floor_area_m2: e.target.value ? Number(e.target.value) : undefined,
            })}
          />
          {invalidArea && <p id="house-area-error" className="error" role="alert">
            Enter a floor area between 10 and 1,000 m².
          </p>}
        </div>
      </div>
    </details>
  )
}
