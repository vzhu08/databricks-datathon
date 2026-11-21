import type { SupabaseClient } from '@supabase/supabase-js';
import { IdentifierSchema, RoomStateSchema, type RoomState } from './index';
/** Presence-backed ephemeral votes. Configure private-channel RLS before allowing client access. */
export async function joinSupabaseRoom(
  client: SupabaseClient,
  room: string,
  userId: string,
  listener: (state: RoomState) => void,
) {
  IdentifierSchema.parse(room);
  IdentifierSchema.parse(userId);
  const channel = client.channel(`kit:${room}`, {
    config: { private: true, presence: { key: userId } },
  });
  let revision = 0;
  channel.on('presence', { event: 'sync' }, () => {
    const presence = channel.presenceState<{ userId: string; choice?: string }>();
    const votes: Record<string, string> = {};
    for (const entries of Object.values(presence))
      for (const entry of entries) if (entry.choice) votes[entry.userId] = entry.choice;
    listener(
      RoomStateSchema.parse({
        room,
        members: Object.keys(presence).sort(),
        votes,
        revision: ++revision,
      }),
    );
  });
  await new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => {
      void client.removeChannel(channel);
      reject(new Error('Realtime subscription timed out'));
    }, 10_000);
    channel.subscribe((status) => {
      if (status === 'SUBSCRIBED') {
        clearTimeout(timeout);
        resolve();
      } else if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT') {
        clearTimeout(timeout);
        void client.removeChannel(channel);
        reject(new Error(status));
      }
    });
  });
  await channel.track({ userId });
  return {
    async vote(choice: string) {
      if (!choice || choice.length > 120) throw new Error('Invalid choice');
      const status = await channel.track({ userId, choice });
      if (status !== 'ok') throw new Error(status);
    },
    async close() {
      await channel.untrack();
      await client.removeChannel(channel);
    },
  };
}
