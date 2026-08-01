import { CanvasStage } from "@/components/CanvasStage";

// `params` is a Promise in Next 16 — synchronous access was removed.
export default async function RoomPage(props: PageProps<"/r/[room]">) {
  const { room } = await props.params;
  return <CanvasStage room={room} />;
}
