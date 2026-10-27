import { researchRequest } from './research';

export type PublishingProfile = {
  id:number; document_version_id:string; document_id:string; project_id:string; project_title:string;
  original_filename:string; revision_number:number; inferred:Record<string,unknown>; corrections:Record<string,unknown>;
  metadata:{ title:string; abstract:string; keywords:string[]; research_field:string; methodology:string; article_type:string;
    word_count:number; references_count:number; research_topics:string[]; section_names:string[] };
};
export type JournalRecord = {
  id:number; provider:'openalex'|'crossref'; provider_id:string; name:string; issns:string[]; publisher:string; website:string;
  subjects:string[]; open_access:boolean|null; doaj_listed:boolean|null; works_count:number|null;
  publication_activity:{year:number;works_count:number}[]; source_url:string; identity_status:string; discrepancies:string[]; verified_at:string;
};
export type JournalRecommendation = { id:number; journal:JournalRecord; score:number; factors:Record<string,{score:number|null;evidence:string}>; missing_evidence:string[] };
export type RecommendationJob = { id:string; profile_id:number; project_title:string; original_filename:string; revision_number:number;
  client_request_id:string; preferences:{open_access_required?:boolean}; status:'queued'|'processing'|'completed'|'partial'|'failed'|'cancelled';
  progress:number; result_count:number; error_category:string; recommendations:JournalRecommendation[] };
export type Readiness = { id:number; document_version_id:string; original_filename:string; project_title:string; revision_number:number;
  checklist:{key:string;label:string;status:'verified_issue'|'potential_issue'|'requires_manual_review'|'not_checked';detail:string}[];
  summary:Record<string,number> };
export type Submission = { id:number; document_version_id:string; journal:JournalRecord|null; status:string; cover_letter:string;
  notes:string; required_files:string[]; checklist:Record<string,unknown>[] };

export const listPublishingProfiles = () => researchRequest<PublishingProfile[]>('publishing/profiles/');
export const createPublishingProfile = (documentVersionId:string) => researchRequest<PublishingProfile>('publishing/profiles/',
  {method:'POST',body:{document_version_id:documentVersionId}});
export const correctPublishingProfile = (id:number, corrections:Record<string,unknown>) => researchRequest<PublishingProfile>(
  `publishing/profiles/${id}/`,{method:'PATCH',body:{corrections}});
export const listRecommendationJobs = () => researchRequest<{count:number;results:RecommendationJob[]}>('publishing/recommendations/');
export const createRecommendationJob = (profileId:number, openAccessRequired:boolean) => researchRequest<RecommendationJob>(
  'publishing/recommendations/',{method:'POST',body:{profile_id:profileId,client_request_id:crypto.randomUUID(),
    consent_to_external_metadata:true,preferences:{open_access_required:openAccessRequired}}});
export const getRecommendationJob = (id:string) => researchRequest<RecommendationJob>(`publishing/recommendations/${id}/`);
export const recommendationAction = (id:string,action:'cancel'|'retry') => researchRequest<RecommendationJob>(`publishing/recommendations/${id}/actions/${action}/`,{method:'POST',body:{}});
export const listSavedJournals = () => researchRequest<{id:number;journal:JournalRecord;note:string}[]>('publishing/saved-journals/');
export const saveJournal = (journalId:number) => researchRequest('publishing/saved-journals/',{method:'POST',body:{journal_id:journalId}});
export const removeSavedJournal = (id:number) => researchRequest<void>(`publishing/saved-journals/${id}/`,{method:'DELETE'});
export const assessReadiness = (versionId:string) => researchRequest<Readiness>('publishing/readiness/',{method:'POST',body:{document_version_id:versionId}});
export const loadSubmission = (versionId:string) => researchRequest<Submission>(`publishing/submissions/?document_version_id=${encodeURIComponent(versionId)}`);
export const saveSubmission = (data:Record<string,unknown>) => researchRequest<Submission>('publishing/submissions/',{method:'PUT',body:data});
export async function downloadReadinessReport(id:number) {
  const response=await fetch(`/api/research/publishing/readiness/${id}/report/`,{credentials:'same-origin',cache:'no-store'});
  if(!response.ok) throw new Error('Readiness report is unavailable.');
  const objectUrl=URL.createObjectURL(await response.blob()); const link=document.createElement('a');
  link.href=objectUrl; link.download=`scholivyn-readiness-${id}.pdf`; link.click(); URL.revokeObjectURL(objectUrl);
}
