/**
 * useMeasurementProfile — D11 profile confirm flow. Loads
 * `GET /tn-measurement-profiles` and preselects
 * `row.publish_draft.suggested_profile_id` (already resolved server-side —
 * no separate `/suggestion` call needed here). The selector is ALWAYS
 * changeable/clearable (task 7.8); applying it to the measurement fields is
 * a separate explicit confirm action owned by `useDraftFields.applyProfile`.
 */
import { useState, useEffect, useCallback } from 'react';
import api from '../../../services/api';

export function useMeasurementProfile({ isOpen, suggestedProfileId }) {
  const [profiles, setProfiles] = useState([]);
  const [loadingProfiles, setLoadingProfiles] = useState(false);
  const [profileError, setProfileError] = useState(null);
  const [selectedProfileId, setSelectedProfileId] = useState(suggestedProfileId ?? null);

  useEffect(() => {
    if (!isOpen) return undefined;
    let cancelled = false;

    async function load() {
      setLoadingProfiles(true);
      setProfileError(null);
      try {
        const response = await api.get('/tn-measurement-profiles');
        if (!cancelled) setProfiles(Array.isArray(response.data) ? response.data : []);
      } catch (err) {
        if (!cancelled) {
          setProfiles([]);
          setProfileError(
            err?.response?.data?.error?.message || err?.message || 'No se pudieron cargar los perfiles de medidas'
          );
        }
      } finally {
        if (!cancelled) setLoadingProfiles(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  const clearProfile = useCallback(() => setSelectedProfileId(null), []);

  return { profiles, loadingProfiles, profileError, selectedProfileId, setSelectedProfileId, clearProfile };
}
