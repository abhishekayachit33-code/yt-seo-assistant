// Mirrors backend/app/report.py's build_report() output. Kept as one flat
// file since the shape is dictated entirely by that one Python function.

export type SeoResult = {
  titles?: string[];
  titles_rationale?: string;
  description?: string;
  tags?: string[];
  tags_rationale?: string;
  hashtags?: string[];
  chapters?: { timestamp: string; title: string }[];
  hook_analysis?: { verdict?: string; reasoning?: string; rewrite?: string };
  suggestions?: string[];
  comment_sentiment?: {
    summary?: string;
    positive_themes?: string[];
    negative_themes?: string[];
  };
  shorts_scripts?: { hook_line: string; script: string; caption: string; rationale?: string }[];
  social_posts?: { twitter_thread?: string; linkedin_post?: string; community_post?: string };
  target_audience?: string;
  audience_next_question?: string;
  content_summary?: string;
  [key: string]: unknown;
};

export type HealthRuleOut = { label: string; passed: boolean; detail: string };

export type KeywordOut = {
  phrase: string;
  score: number;
  specificity: number;
  coverage: number;
  autocomplete_strength: number;
  relevance: number;
  intent: string;
  evidence: string[];
  autocomplete_rank: number | null;
  competitor_hits: number;
};

export type KeywordStrategyOut = {
  primary: KeywordOut | null;
  secondary: KeywordOut[];
  long_tail: KeywordOut[];
  lanes_used: string[];
  confidence: "low" | "medium" | "high";
  confidence_reason: string;
};

export type AudienceGapOut = {
  competitor_median_views: number;
  gap: number;
  has_outliers: boolean;
  missing_tags: { tag: string; competitor_count: number }[];
  top_competitors: {
    video_id: string; title: string; channel_title: string; tags: string[]; view_count: number;
  }[];
  outliers: { video_id: string; title: string; channel_title: string; view_count: number }[];
};

export type ReportOut = {
  analysis_id: number | null;
  video_id: string;
  title: string;
  channel: string;
  thumbnail_url: string;
  live: boolean;
  planning: boolean;
  note: string;
  result: SeoResult;
  original_score: number;
  optimized_score: number;
  optimized_rules: HealthRuleOut[];
  audience_gap: AudienceGapOut | null;
  shelf_life: {
    evergreen_score: number; classification: string; expectation: string;
    evergreen_hits: string[]; trending_hits: string[]; is_unclassified: boolean;
  };
  cta_report: {
    duration: number; recommended_timestamp: string; has_well_placed: boolean;
    mentions: { seconds: number; position: number; label: string; text: string; zone: string; timestamp: string }[];
    stranded: { timestamp: string; label: string; position: number }[];
  } | null;
  readability: {
    filler_hits: { word: string; count: number }[];
    total_filler_count: number; word_count: number; sentence_count: number;
    avg_sentence_length: number; filler_rate: number;
  } | null;
  speech_estimate: { word_count: number; low_minutes: number; high_minutes: number; label: string } | null;
  pacing: {
    average_wpm: number;
    blocks: { minute: number; wpm: number }[];
    silent_gap_threshold_seconds: number;
    silent_gaps: { start: number; end: number; duration: number }[];
  } | null;
  performance: {
    views: number; likes: number; comments: number; days_since_upload: number;
    views_per_day: number; engagement_rate: number;
  } | null;
  projection: {
    projection_days: number; score_delta: number; low_uplift: number; high_uplift: number;
    baseline_views: number; low_views: number; high_views: number;
  } | null;
  revenue: {
    current: number; category_name: string; rpm: number;
    additional_low: number; additional_high: number; is_known_category: boolean;
  } | null;
  playbook: { title: string; detail: string; icon: string }[];
  preproduction_checklist: {
    ready_to_record: boolean;
    items: { label: string; status: string; detail: string }[];
  } | null;
  tag_diff: { added: string[]; kept: string[]; removed: string[] } | null;
  description_diff: string[];
  top_comments: string[];
  keyword_strategy: KeywordStrategyOut | null;
  variants: { title: string; result: SeoResult }[] | null;
  warning?: string | null;
};
