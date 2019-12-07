from gimpfu import *


# We are assuming a 300 dpi images
DPI = 300


class PausedUndo:
    def __init__(self, image):
        self.image = image

    def __enter__(self):
        self.image.disable_undo()
        return None

    def __exit__(self, type, value, traceback):
        self.image.enable_undo()
        return False


class DefaultContext:
    def __enter__(self):
        gimp.context_push()
        pdb.gimp_context_set_defaults()
        return None

    def __exit__(self, type, value, traceback):
        gimp.context_pop()
        return False


class Corner:
    TOP_LEFT = 1
    TOP_RIGHT = 2
    BOTTOM_LEFT = 3
    BOTTOM_RIGHT = 4
    CENTER = 5


class Direction:
    LEFT = 1
    RIGHT = 2
    UP = 3
    DOWN = 4


def mm_to_px(mm):
    # type: (float) -> None
    return int(round(mm / 25.4 * DPI))


def px_to_mm(px):
    return (px * 25.4) / DPI


def get_layer_by_name(image, layer_name):
    for layer in image.layers:
        if layer.name == layer_name:
            return layer
    gimp.message("Layer %s not found" % layer_name)
    return None


def move_drawable_to(drawable, corner, x, y):
    left, top = pdb.gimp_drawable_offsets(drawable)
    width, height = pdb.gimp_drawable_mask_bounds(drawable)[3:]
    right = left + width
    bottom = top + height
    dx, dy = 0, 0
    if corner == Corner.TOP_LEFT:
        dx = x - left
        dy = y - top
    elif corner == Corner.TOP_RIGHT:
        dx = x - right
        dy = y - top
    elif corner == Corner.BOTTOM_LEFT:
        dx = x - left
        dy = y - bottom
    elif corner == Corner.BOTTOM_RIGHT:
        dx = x - right
        dy = y - bottom
    elif corner == Corner.CENTER:
        dx = x - (left + right) // 2
        dy = y - (top + bottom) // 2
    else:
        gimp.message("Invalid corner %s" % repr(corner))
        return
    pdb.gimp_layer_translate(drawable, dx, dy)


def copy_and_rotate_rectangle(src_image, src_x, src_y, src_width, src_height,
                              dst_image, dst_layer, dst_x, dst_y, dst_corner,
                              angle):
    pdb.gimp_image_select_rectangle(src_image, CHANNEL_OP_REPLACE,
                                    src_x, src_y, src_width, src_height)
    pdb.gimp_edit_copy_visible(src_image)
    pdb.gimp_selection_none(src_image)

    # Paste into dst as a floating selection
    floating = pdb.gimp_edit_paste(dst_layer, TRUE)

    # Rotate floating selection if needed
    angles = {90: ROTATE_90, 180: ROTATE_180, 270: ROTATE_270}
    if angle in angles:
        rotation = angles[angle]
        pdb.gimp_drawable_transform_rotate_simple(
            floating, rotation, FALSE, 0, 0, FALSE)

    # Move floating selection into position and anchor it
    move_drawable_to(floating, dst_corner, dst_x, dst_y)
    pdb.gimp_floating_sel_anchor(floating)


def draw_mark(image, directions, x0, y0, size, distance):
    x, y, width, height = 0, 0, 0, 0

    for direction in directions:
        if direction == Direction.UP:
            x = x0 - 1
            y = y0 - distance - size
            width = 2
            height = size
        elif direction == Direction.DOWN:
            x = x0 - 1
            y = y0 + distance
            width = 2
            height = size
        elif direction == Direction.LEFT:
            x = x0 - distance - size
            y = y0 - 1
            width = size
            height = 2
        elif direction == Direction.RIGHT:
            x = x0 + distance
            y = y0 - 1
            width = size
            height = 2
        else:
            gimp.message("Invalid direction %s" % repr(directon))
            return

        pdb.gimp_image_select_rectangle(
            image, CHANNEL_OP_REPLACE, x, y, width, height)
        pdb.gimp_edit_fill(image.active_layer, FILL_FOREGROUND)
        pdb.gimp_selection_none(image)


def template_coordinates(box_width, box_height, box_depth):
    # The template layout looks like this:
    #
    #    x0         x1         x2        x3         x4
    #
    # y0 o          +----------+                       -
    #               |          |                       ^
    #               |   TOP    |                       | depth
    #               |          |                       v
    # y1 +----------+----------+---------+----------+  -
    #    |          |          |         |          |  ^
    # y2 |---LEFT---|--FRONT---|--RIGHT--|---BACK---|  | height
    #    |          |          |         |          |  v
    # y3 +----------+----------+---------+----------+  -
    #               |          |                       ^
    #               |  BOTTOM  |                       | depth
    #               |          |                       v
    # y4            +----------+                       -
    #
    #     |<------->|<-------->|<------->|<-------->|
    #        depth     width      depth     width

    x0 = 0
    x1 = x0 + box_depth
    x2 = x1 + box_width
    x3 = x2 + box_depth
    x4 = x3 + box_width

    y0 = 0
    y1 = y0 + box_depth
    y2 = y1 + box_height // 2
    y3 = y1 + box_height
    y4 = y3 + box_depth

    return ((x0, x1, x2, x3, x4), (y0, y1, y2, y3, y4))


def wrap_coordinates(box_width, box_height, box_depth,
                     thickness, inside_size, flap_size,
                     crop_mark_size, crop_mark_distance):
    # The wrap layout looks like this:
    #     0   x1      x2 x3       x4  x5           x6  x7      x8 x9      x10 x11
    #
    # 0   o                       |   |            |   |
    #
    # y1                      --  +---+------------+---+  --
    #                             |   |            |   |
    #                             |   |  inside    |   |
    #                             |   |            |   |
    # y2                          +...+............+...+
    #                             |   |            |   |
    # y3                          +...+............+...+
    #                             | f |            | f |
    #                             | l |   front    | l |
    #         |                   | a |   /back    | a |                   |
    #                             | p |            | p |
    # y4  --  +--------+-+--------+---+------------+---+--------+-+--------+  --
    # y5      |........|.|............|            |............|.|........|
    #         | inside | | left/right | top/bottom | left/right | | inside |
    # y6      |........|.|............|            |............|.|........|
    # y7  --  +--------+-+--------+---+------------+---+--------+-+--------+  --
    #                             | f |            | f |
    #         |                   | l |   front    | l |                   |
    #                             | a |   /back    | a |
    #                             | p |            | p |
    # y8                          +...+............+...+
    #                             |   |            |   |
    # y9                          +...+............+...+
    #                             |   |            |   |
    #                             |   |  inside    |   |
    #                             |   |            |   |
    # y10                     --  +---+------------+---+  --
    #
    # y11                         |   |            |   |

    half_box_height = box_height // 2

    x1 = crop_mark_size + crop_mark_distance
    x2 = x1 + inside_size
    x3 = x2 + thickness
    x5 = x3 + half_box_height
    x4 = x5 - flap_size
    x6 = x5 + box_width
    x7 = x6 + flap_size
    x8 = x6 + half_box_height
    x9 = x8 + thickness
    x10 = x9 + inside_size
    x11 = x10 + crop_mark_distance + crop_mark_size

    y1 = crop_mark_size + crop_mark_distance
    y2 = y1 + inside_size
    y3 = y2 + thickness
    y4 = y3 + half_box_height
    y5 = y4 + flap_size
    y7 = y4 + box_depth
    y6 = y7 - flap_size
    y8 = y7 + half_box_height
    y9 = y8 + thickness
    y10 = y9 + inside_size
    y11 = y10 + crop_mark_distance + crop_mark_size

    return ((0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11),
            (0, y1, y2, y3, y4, y5, y6, y7, y8, y9, y10, y11))


def create_template(box_width_mm, box_height_mm, box_depth_mm):
    with DefaultContext():
        box_width = mm_to_px(box_width_mm)
        box_height = mm_to_px(box_height_mm)
        box_depth = mm_to_px(box_depth_mm)

        xs, ys = template_coordinates(box_width, box_height, box_depth)
        image_width = xs[-1] - xs[0]
        image_height = ys[-1] - ys[0]

        # Create a template image with one transparent layer
        image = gimp.Image(image_width, image_height)

        with PausedUndo(image):
            layer = gimp.Layer(image, "Template", image_width, image_height,
                               RGBA_IMAGE, 100, NORMAL_MODE)
            image.add_layer(layer, 0)

            # Create guides
            for x in xs:
                image.add_vguide(x)
            for y in ys:
                image.add_hguide(y)

            # Fill the areas where the graphics go with white
            pdb.gimp_selection_none(image)
            pdb.gimp_progress_pulse()
            pdb.gimp_image_select_rectangle(
                image, CHANNEL_OP_ADD, xs[0], ys[1], image_width, ys[3]-ys[1])
            pdb.gimp_progress_pulse()
            pdb.gimp_image_select_rectangle(
                image, CHANNEL_OP_ADD, xs[1], ys[0], xs[2]-xs[1], image_height)
            pdb.gimp_edit_fill(layer, FILL_WHITE)
            pdb.gimp_selection_none(image)

            # Put some text in the center a rectangle
            def put_text(text, left, right, top, bottom):
                pdb.gimp_progress_pulse()
                text_size = DPI / 4  # quarter inch
                text_layer = pdb.gimp_text_layer_new(
                    image, text, "sans-serif", text_size, PIXELS)
                image.add_layer(text_layer, 0)
                move_drawable_to(text_layer, Corner.CENTER,
                                 (left + right) // 2, (top + bottom) // 2)
                pdb.gimp_image_merge_down(
                    image, text_layer, CLIP_TO_BOTTOM_LAYER)

            put_text("TOP", xs[1], xs[2], ys[0], ys[1])
            put_text("LEFT", xs[0], xs[1], ys[1], ys[3])
            put_text("FRONT", xs[1], xs[2], ys[1], ys[3])
            put_text("RIGHT", xs[2], xs[3], ys[1], ys[3])
            put_text("BACK", xs[3], xs[4], ys[1], ys[3])
            put_text("BOTTOM", xs[1], xs[2], ys[3], ys[4])
            put_text("Box width: %dmm (%dpx)\n"
                     "Box height: %dmm (%dpx)\n"
                     "Box depth: %dmm (%dpx)" %
                     (box_width_mm, box_width,
                      box_height_mm, box_height,
                      box_depth_mm, box_depth),
                     xs[0], xs[1], ys[0], ys[1])

            gimp.Display(image)
    gimp.displays_flush()


def create_wraps(src_image,
                 box_width_mm, box_height_mm, box_depth_mm,
                 thickness_mm, flap_size_mm, inside_size_mm,
                 crop_mark_size_mm, crop_mark_distance_mm):
    # Convert the dimensions from mm to px
    box_width = mm_to_px(box_width_mm)
    box_height = mm_to_px(box_height_mm)
    box_depth = mm_to_px(box_depth_mm)
    thickness = mm_to_px(thickness_mm)
    flap_size = mm_to_px(flap_size_mm)
    inside_size = mm_to_px(inside_size_mm)
    crop_mark_size = mm_to_px(crop_mark_size_mm)
    crop_mark_distance = mm_to_px(crop_mark_distance_mm)

    half_box_height = box_height // 2
    half_box_height_plus_extra = half_box_height + thickness + inside_size

    # Coordinates in the source image
    src_xs, src_ys = template_coordinates(box_width, box_height, box_depth)
    src_image_width = src_xs[-1] - src_xs[0]
    src_image_height = src_ys[-1] - src_ys[0]

    # Coordinates in the destination images
    dst_xs, dst_ys = wrap_coordinates(box_width, box_height, box_depth,
                                      thickness, inside_size, flap_size,
                                      crop_mark_size, crop_mark_distance)
    dst_image_width = dst_xs[-1] - dst_xs[0]
    dst_image_height = dst_ys[-1] - dst_ys[0]

    # Make sure we have the right dimensions
    if src_image.width != src_image_width or \
       src_image.height != src_image_height:
        gimp.message("Template image has the wrong size. "
                     "Expected %dpx x %dpx (%dmm x %dmm) "
                     "but got %dpx x %dpx (%dmm x %dmm)."
                     % (src_image_width,
                        src_image_height,
                        px_to_mm(src_image_width),
                        px_to_mm(src_image_height),
                        src_image.width,
                        src_image_height,
                        px_to_mm(src_image.width),
                        px_to_mm(src_image.height)))
        return

    # Draw stuff onto both destination images in the same way
    def draw(dst_image, copy_and_rotate_definitions):
        dst_layer = gimp.Layer(dst_image, "Wrap", dst_image_width,
                               dst_image_height, RGB_IMAGE, 100, NORMAL_MODE)
        dst_layer.fill(FILL_WHITE)
        dst_image.add_layer(dst_layer, 0)

        # Add guides
        for x in dst_xs:
            dst_image.add_vguide(x)
        for y in dst_ys:
            dst_image.add_hguide(y)

        # Take the layers from the template and move and rotate them into position
        for d in copy_and_rotate_definitions:
            pdb.gimp_progress_pulse()
            copy_and_rotate_rectangle(
                src_image,      # src_image
                d[0],           # src_x
                d[1],           # src_y
                d[2],           # src_width
                d[3],           # src_height
                dst_image,      # dst_image
                dst_layer,      # dst_layer
                d[4],           # dst_x
                d[5],           # dst_y
                d[6],           # dst_corner
                d[7])           # rotation_angle

        # Copy strips from the sides to create the flaps on the front and the back
        pdb.gimp_progress_pulse()
        copy_and_rotate_rectangle(
            dst_image, dst_xs[1], dst_ys[4], half_box_height_plus_extra, flap_size,
            dst_image, dst_layer, dst_xs[5], dst_ys[4], Corner.BOTTOM_RIGHT, 90)
        pdb.gimp_progress_pulse()
        copy_and_rotate_rectangle(
            dst_image, dst_xs[1], dst_ys[6], half_box_height_plus_extra, flap_size,
            dst_image, dst_layer, dst_xs[5], dst_ys[7], Corner.TOP_RIGHT, 270)
        pdb.gimp_progress_pulse()
        copy_and_rotate_rectangle(
            dst_image, dst_xs[6], dst_ys[4], half_box_height_plus_extra, flap_size,
            dst_image, dst_layer, dst_xs[6], dst_ys[4], Corner.BOTTOM_LEFT, 270)
        pdb.gimp_progress_pulse()
        copy_and_rotate_rectangle(
            dst_image, dst_xs[6], dst_ys[6], half_box_height_plus_extra, flap_size,
            dst_image, dst_layer, dst_xs[6], dst_ys[7], Corner.TOP_LEFT, 90)

        # Marks for cutting and folding
        draw_mark(dst_image, (Direction.UP, Direction.LEFT),
                  dst_xs[4], dst_ys[1], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.UP,),
                  dst_xs[5], dst_ys[1], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.UP,),
                  dst_xs[6], dst_ys[1], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.UP, Direction.RIGHT),
                  dst_xs[7], dst_ys[1], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.UP, Direction.LEFT),
                  dst_xs[1], dst_ys[4], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.UP, Direction.RIGHT),
                  dst_xs[10], dst_ys[4], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN, Direction.LEFT),
                  dst_xs[1], dst_ys[7], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN, Direction.RIGHT),
                  dst_xs[10], dst_ys[7], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN, Direction.LEFT),
                  dst_xs[4], dst_ys[10], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN,),
                  dst_xs[5], dst_ys[10], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN,),
                  dst_xs[6], dst_ys[10], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN, Direction.RIGHT),
                  dst_xs[7], dst_ys[10], crop_mark_size, crop_mark_distance)

        pdb.gimp_selection_none(dst_image)

    # Define where from and where to we want to copy
    # Each line looks like this:
    # (src_x, src_y, src_width, src_height,
    #  dst_x, dst_y, dst_corner, rotation_angle)
    copy_and_rotate_definitions_top = (
        # Top
        (src_xs[1], src_ys[0], box_width, box_depth,
         dst_xs[5], dst_ys[4], Corner.TOP_LEFT, 0),
        # Left
        (src_xs[0], src_ys[1], box_depth, half_box_height_plus_extra,
         dst_xs[5], dst_ys[4], Corner.TOP_RIGHT, 90),
        # Front
        (src_xs[1], src_ys[1], box_width, half_box_height_plus_extra,
         dst_xs[5], dst_ys[7], Corner.TOP_LEFT, 0),
        # Right
        (src_xs[2], src_ys[1], box_depth, half_box_height_plus_extra,
         dst_xs[6], dst_ys[4], Corner.TOP_LEFT, 270),
        # Back
        (src_xs[3], src_ys[1], box_width, half_box_height_plus_extra,
         dst_xs[5], dst_ys[4], Corner.BOTTOM_LEFT, 180),
    )

    copy_and_rotate_definitions_bottom = (
        # Left
        (src_xs[0], src_ys[3] - half_box_height_plus_extra, box_depth,
         half_box_height_plus_extra, dst_xs[5], dst_ys[4], Corner.TOP_RIGHT, 270),
        # Front
        (src_xs[1], src_ys[3] - half_box_height_plus_extra, box_width,
         half_box_height_plus_extra, dst_xs[5], dst_ys[1], Corner.TOP_LEFT, 0),
        # Right
        (src_xs[2], src_ys[3] - half_box_height_plus_extra, box_depth,
         half_box_height_plus_extra, dst_xs[6], dst_ys[4], Corner.TOP_LEFT, 90),
        # Back
        (src_xs[3], src_ys[3] - half_box_height_plus_extra, box_width,
         half_box_height_plus_extra, dst_xs[5], dst_ys[10], Corner.BOTTOM_LEFT, 180),
        # Bottom
        (src_xs[1], src_ys[3], box_width, box_depth,
         dst_xs[5], dst_ys[4], Corner.TOP_LEFT, 0),
    )

    with DefaultContext():
        dst_image_top = gimp.Image(dst_image_width, dst_image_height, RGB)
        with PausedUndo(dst_image_top):
            draw(dst_image_top, copy_and_rotate_definitions_top)
            gimp.Display(dst_image_top)

        dst_image_bottom = gimp.Image(dst_image_width, dst_image_height, RGB)
        with PausedUndo(dst_image_bottom):
            draw(dst_image_bottom, copy_and_rotate_definitions_bottom)
            gimp.Display(dst_image_bottom)
    gimp.displays_flush()


plugin_author = "Elam Kolenovic"
plugin_copyright = "Elam Kolenovic"
plugin_date = "2019-11-23"
plugin_menu = "<Toolbox>/Filters/Boardgames/Box Wrap/"

register(
    "Boxwrap_Create_Template",
    "Box width: Distance between left and right face\n"
    "Box height: Distance between top and bottom face\n"
    "Box depth: Distance between front and back face\n",
    "Create an empty template image for the printable box wrap",
    plugin_author,
    plugin_copyright,
    plugin_date,
    plugin_menu + "Create empty template...",
    "",
    [
        (PF_ADJUSTMENT, "width", "Box width [mm]", 75, (10, 500, 1)),
        (PF_ADJUSTMENT, "height", "Box height [mm]", 104, (10, 500, 1)),
        (PF_ADJUSTMENT, "depth", "Box depth [mm]", 100, (10, 500, 1))
    ],
    [],
    create_template
)

register(
    "Boxwrap_Create_Wraps",
    "The dimensions must be the same as in the template dialog!\n"
    "\n"
    "Box width: Distance between left and right face\n"
    "Box height: Distance between top and bottom face\n"
    "Box depth: Distance between front and back face\n",
    "Create the printable wraps for both halves of the box from the template image",
    plugin_author,
    plugin_copyright,
    plugin_date,
    plugin_menu + "Create wraps from template...",
    "RGB*",
    [
        (PF_IMAGE, "image", "Template with six layers", 0),
        (PF_ADJUSTMENT, "width", "Box width [mm]", 75, (10, 500, 1)),
        (PF_ADJUSTMENT, "height", "Box height [mm]", 104, (10, 500, 1)),
        (PF_ADJUSTMENT, "depth", "Box depth [mm]", 100, (10, 500, 1)),
        (PF_ADJUSTMENT, "thickness",
         "Cardboard thickness [mm]", 2.0, (0.5, 6.0, 0.5)),
        (PF_ADJUSTMENT, "flap_size",
         "Width of the flaps [mm]", 10.0, (1.0, 20.0, 1.0)),
        (PF_ADJUSTMENT, "inside_size",
         "Amount of paper inside the box [mm]", 15.0, (1.0, 50.0, 1.0)),
        (PF_ADJUSTMENT, "crop_mark_size",
         "Size of the crop marks [mm]", 5.0, (1.0, 20.0, 1.0)),
        (PF_ADJUSTMENT, "crop_mark_distance",
         "Distance between the crop marks and the image [mm]", 2.0, (0.0, 10.0, 1.0))
    ],
    [],
    create_wraps
)

main()
