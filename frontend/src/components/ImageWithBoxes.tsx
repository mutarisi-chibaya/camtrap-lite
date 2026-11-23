import { type DetectionOut, imageUrl } from "../api/client";
import { boxStyle } from "./boxes";

interface Props {
  imageId: number;
  detections: DetectionOut[];
  minConf: number; // boxes below this are hidden (they can't change triage)
  alt: string;
}

/**
 * The image plus its detection boxes. Boxes are absolutely positioned in percent, so they
 * stay aligned however the browser scales the image; no canvas needed.
 */
export default function ImageWithBoxes({ imageId, detections, minConf, alt }: Props) {
  return (
    <div className="boxed-image">
      <img src={imageUrl(imageId)} alt={alt} draggable={false} />
      {detections
        .filter((d) => d.confidence >= minConf)
        .map((d) => (
          <div
            key={d.id}
            className={`box box-${d.category}${d.is_static_candidate ? " box-static" : ""}`}
            style={boxStyle(d.bbox)}
          >
            <span className="box-label">
              {d.category} {d.confidence.toFixed(2)}
              {d.is_static_candidate ? " · static?" : ""}
            </span>
          </div>
        ))}
    </div>
  );
}
