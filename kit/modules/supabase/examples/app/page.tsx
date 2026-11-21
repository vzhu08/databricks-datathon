import { AuthNotesDemo } from '../components/AuthNotesDemo';
export default function Page() {
  const mode = process.env.NEXT_PUBLIC_SUPABASE_EXAMPLE_MODE === 'live' ? 'live' : 'fixture';
  return <AuthNotesDemo mode={mode} githubOAuth={process.env.KIT_EXAMPLE_GITHUB_OAUTH === '1'} />;
}
