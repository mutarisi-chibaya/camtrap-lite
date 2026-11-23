import { imageUrl } from "../api/client";
import { boxStyle, cropStyle } from "./boxes";

interface Props {
  imageId: number;
  bbox: [number, number, number, number];
  aspect: number; // image width / height
  caption?: string;
}

/** A zoomed crop around one box, with the box outlined. Pure CSS: no server-side cropping. */
export default function BoxCrop({ imageId, bbox, aspect, caption }: Props) {
  return (
    <figure className="crop">
      <div className="crop-frame" style={{ aspectRatio: String(aspect) }}>
        <div className="crop-inner" style={cropStyle(bbox)}>
          <img src={imageUrl(imageId)} alt="" loading="lazy" draggable={false} />
          <div className="box box-static" style={boxStyle(bbox)} />
        </div>
      </div>
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}
