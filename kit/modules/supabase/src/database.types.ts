/** Schema snapshot for migrations/001_notes.sql. Regenerate after coordinated migrations with the command in README. */
export type Database = {
  public: {
    Tables: {
      kit_notes: {
        Row: { id: string; owner_id: string; title: string; body: string; created_at: string };
        Insert: {
          id?: string;
          owner_id: string;
          title: string;
          body?: string;
          created_at?: string;
        };
        Update: { title?: string; body?: string };
        Relationships: [];
      };
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
    Enums: Record<string, never>;
    CompositeTypes: Record<string, never>;
  };
};
