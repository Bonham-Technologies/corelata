import { useMutation, useQuery } from "@tanstack/react-query";
import { client, unwrap } from "./client";
import type { DoctorReport, SystemInfo } from "./types";

export const systemKeys = {
  info: ["system", "info"] as const,
  doctor: ["system", "doctor"] as const,
};

/** Who is calling, which version answers, and what the deployment offers (spec §10.1 info). */
export function useInfo() {
  return useQuery({
    queryKey: systemKeys.info,
    queryFn: ({ signal }) => unwrap<SystemInfo>(client.GET("/api/system/info", { signal })),
    staleTime: Infinity,
  });
}

/** Settings ▸ Status (M18 spec §5.6): the installation checks without test completions, read
 * when the page opens. Copied from Coglossa's useDoctorStatus. */
export function useDoctorStatus() {
  return useQuery({
    queryKey: systemKeys.doctor,
    queryFn: ({ signal }) =>
      unwrap<DoctorReport>(
        client.GET("/api/system/doctor", { params: { query: { probe: false } }, signal }),
      ),
  });
}

/** Settings ▸ Run a full check: the checks with a test completion per model (probe=true).
 * Copied from Coglossa's useDoctor. */
export function useDoctor() {
  return useMutation({
    mutationFn: () =>
      unwrap<DoctorReport>(
        client.GET("/api/system/doctor", { params: { query: { probe: true } } }),
      ),
  });
}
